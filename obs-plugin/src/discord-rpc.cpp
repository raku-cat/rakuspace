#include "discord-rpc.hpp"
#include "rakuspace-config.h"
#include "vendor/nlohmann/json.hpp"

#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <mutex>
#include <string>

#ifdef _WIN32
#include <windows.h>
#else
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <cstdlib>
#endif

using json = nlohmann::json;

namespace rakuspace {

namespace {

std::string make_nonce()
{
	static std::atomic<uint64_t> counter{0};
	return std::to_string(::time(nullptr)) + "-" + std::to_string(counter.fetch_add(1));
}

json activity_to_json(const Activity &a)
{
	json act;
	act["details"] = a.details;
	if (!a.state.empty())
		act["state"] = a.state;
	if (a.start_ts > 0)
		act["timestamps"] = {{"start", a.start_ts}};
	if (!a.large_image.empty()) {
		act["assets"]["large_image"] = a.large_image;
		if (!a.large_text.empty())
			act["assets"]["large_text"] = a.large_text;
	}
	if (!a.button_label.empty() && !a.button_url.empty())
		act["buttons"] = json::array({{{"label", a.button_label}, {"url", a.button_url}}});
	return act;
}

} // namespace

// ---- platform pipe I/O -------------------------------------------------------

#ifdef _WIN32

struct PipeHandle {
	HANDLE h = INVALID_HANDLE_VALUE;
	bool valid() const { return h != INVALID_HANDLE_VALUE; }
	void reset()
	{
		if (valid())
			CloseHandle(h);
		h = INVALID_HANDLE_VALUE;
	}
};

static bool pipe_open(PipeHandle &p)
{
	for (int i = 0; i < 10; ++i) {
		char name[64];
		std::snprintf(name, sizeof(name), "\\\\.\\pipe\\discord-ipc-%d", i);
		HANDLE h = CreateFileA(name, GENERIC_READ | GENERIC_WRITE, 0, nullptr,
				       OPEN_EXISTING, 0, nullptr);
		if (h != INVALID_HANDLE_VALUE) {
			p.h = h;
			return true;
		}
	}
	return false;
}

static bool pipe_write_all(PipeHandle &p, const char *buf, size_t len)
{
	while (len > 0) {
		DWORD wrote = 0;
		if (!WriteFile(p.h, buf, (DWORD)len, &wrote, nullptr) || wrote == 0)
			return false;
		buf += wrote;
		len -= wrote;
	}
	return true;
}

static bool pipe_read_all(PipeHandle &p, char *buf, size_t len)
{
	while (len > 0) {
		DWORD got = 0;
		if (!ReadFile(p.h, buf, (DWORD)len, &got, nullptr) || got == 0)
			return false;
		buf += got;
		len -= got;
	}
	return true;
}

#else

struct PipeHandle {
	int fd = -1;
	bool valid() const { return fd >= 0; }
	void reset()
	{
		if (valid())
			::close(fd);
		fd = -1;
	}
};

static bool pipe_open(PipeHandle &p)
{
	const char *base = std::getenv("XDG_RUNTIME_DIR");
	const char *dirs[] = {base, "/tmp", nullptr};
	for (int d = 0; dirs[d]; ++d) {
		if (!dirs[d] || !dirs[d][0])
			continue;
		for (int i = 0; i < 10; ++i) {
			struct sockaddr_un addr;
			std::memset(&addr, 0, sizeof(addr));
			addr.sun_family = AF_UNIX;
			std::snprintf(addr.sun_path, sizeof(addr.sun_path),
				      "%s/discord-ipc-%d", dirs[d], i);
			int fd = ::socket(AF_UNIX, SOCK_STREAM, 0);
			if (fd < 0)
				continue;
			if (::connect(fd, (struct sockaddr *)&addr, sizeof(addr)) == 0) {
				p.fd = fd;
				return true;
			}
			::close(fd);
		}
	}
	return false;
}

static bool pipe_write_all(PipeHandle &p, const char *buf, size_t len)
{
	while (len > 0) {
		ssize_t wrote = ::send(p.fd, buf, len, MSG_NOSIGNAL);
		if (wrote <= 0)
			return false;
		buf += wrote;
		len -= (size_t)wrote;
	}
	return true;
}

static bool pipe_read_all(PipeHandle &p, char *buf, size_t len)
{
	while (len > 0) {
		ssize_t got = ::read(p.fd, buf, len);
		if (got <= 0)
			return false;
		buf += got;
		len -= (size_t)got;
	}
	return true;
}

#endif

// ---- framing ---------------------------------------------------------------

namespace {

bool send_frame(PipeHandle &p, uint32_t op, const std::string &payload)
{
	char header[8];
	uint32_t len = (uint32_t)payload.size();
	std::memcpy(header, &op, 4);      // x86/x64 little-endian; targets are LE
	std::memcpy(header + 4, &len, 4);
	if (!pipe_write_all(p, header, 8))
		return false;
	return pipe_write_all(p, payload.data(), payload.size());
}

// Reads one frame and discards it. Used to drain the READY/ack responses.
bool drain_frame(PipeHandle &p)
{
	char header[8];
	if (!pipe_read_all(p, header, 8))
		return false;
	uint32_t len = 0;
	std::memcpy(&len, header + 4, 4);
	if (len == 0)
		return true;
	if (len > 64 * 1024)
		return false;
	std::string body(len, '\0');
	return pipe_read_all(p, &body[0], len);
}

} // namespace

// ---- DiscordRpc ----------------------------------------------------------

struct DiscordRpc::Impl {
	std::mutex mtx;
	PipeHandle pipe;
	std::atomic<bool> ready{false};
};

DiscordRpc &DiscordRpc::instance()
{
	static DiscordRpc inst;
	return inst;
}

DiscordRpc::DiscordRpc() : impl_(new Impl) {}
DiscordRpc::~DiscordRpc() { close(); delete impl_; }

bool DiscordRpc::connected() const
{
	return impl_->ready;
}

bool DiscordRpc::connect()
{
	std::lock_guard<std::mutex> lk(impl_->mtx);
	if (impl_->ready)
		return true;
	if (!pipe_open(impl_->pipe))
		return false;
	json hs = {{"v", 1}, {"client_id", RAKUSPACE_DISCORD_APP_ID}};
	if (!send_frame(impl_->pipe, 0, hs.dump())) {
		impl_->pipe.reset();
		return false;
	}
	if (!drain_frame(impl_->pipe)) { // READY
		impl_->pipe.reset();
		return false;
	}
	impl_->ready = true;
	return true;
}

bool DiscordRpc::set_activity(const Activity &a)
{
	std::lock_guard<std::mutex> lk(impl_->mtx);
	if (!impl_->ready)
		return false;
	try {
		json msg = {
			{"cmd", "SET_ACTIVITY"},
			{"nonce", make_nonce()},
			{"args", {{"pid", (int)
#ifdef _WIN32
					 GetCurrentProcessId()
#else
					 ::getpid()
#endif
				  },
				  {"activity", activity_to_json(a)}}},
		};
		if (!send_frame(impl_->pipe, 1, msg.dump())) {
			impl_->pipe.reset();
			impl_->ready = false;
			return false;
		}
		if (!drain_frame(impl_->pipe)) { // ack; ignore contents
			impl_->pipe.reset();
			impl_->ready = false;
		}
		return true;
	} catch (...) {
		return false;
	}
}

bool DiscordRpc::clear()
{
	std::lock_guard<std::mutex> lk(impl_->mtx);
	if (!impl_->ready)
		return false;
	json msg = {
		{"cmd", "SET_ACTIVITY"},
		{"nonce", make_nonce()},
		{"args", {{"pid", (int)
#ifdef _WIN32
				 GetCurrentProcessId()
#else
				 ::getpid()
#endif
			  },
			  {"activity", nullptr}}},
	};
	if (!send_frame(impl_->pipe, 1, msg.dump())) {
		impl_->pipe.reset();
		impl_->ready = false;
		return false;
	}
	if (!drain_frame(impl_->pipe)) {
		impl_->pipe.reset();
		impl_->ready = false;
	}
	return true;
}

void DiscordRpc::close()
{
	std::lock_guard<std::mutex> lk(impl_->mtx);
	impl_->pipe.reset();
	impl_->ready = false;
}

} // namespace rakuspace

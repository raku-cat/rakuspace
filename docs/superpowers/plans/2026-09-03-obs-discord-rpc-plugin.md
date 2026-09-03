# OBS RakuSpace Service + Discord RPC Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an OBS Studio plugin that adds a first-class "RakuSpace" streaming service and an optional Discord Rich Presence card while live, plus the one supporting change to the Flask app it needs.

**Architecture:** A single C++ OBS module in a new top-level `obs-plugin/` directory, built from the official `obs-plugin-template`. Three internal units: a registered streaming service (`rakuspace-service`), a minimal Discord IPC client (`discord-rpc`), and glue (`plugin-main`) that reacts to OBS streaming start/stop events. The Flask side gains one field on an existing JSON endpoint.

**Tech Stack:** C++17, libobs + obs-frontend-api (OBS 30.1+), CMake presets, libcurl (bundled with OBS), vendored `nlohmann/json` single header. Flask/Python 3 + pytest for the frontend change.

## Global Constraints

Every task's requirements implicitly include these (verbatim from the spec):

- **OBS 30.1 is the minimum version.** Implement only the modern `get_connect_info` service path; do not implement pre-30.1 `get_url`/`get_key`.
- **Target platform is Windows x64.** Plugin stays cross-platform-buildable for local compile-checks on Linux; Windows is the only tested and shipped target. macOS build jobs/presets are removed.
- The service registration must **not** set `OBS_SERVICE_INTERNAL` (it must appear in the Settings → Stream service list).
- **Deployment-specific values are baked-in constants**, documented as the edit points for another deployment: `RAKUSPACE_RTMP_INGEST`, `RAKUSPACE_SITE_BASE` (`https://rakuspace.site`), `RAKUSPACE_DISCORD_APP_ID`.
- Discord Rich Presence requires **no review submission** (that is Activities, not Rich Presence).
- The username field is **display/link only** — never used for publish auth.
- **No unit-test harness for the OBS plugin** (signed off). Verification for C++ tasks is: a clean build via the CMake presets, plus the specific manual test-matrix item(s) named in the task. The Flask task uses real pytest.
- Deliberately excluded, do not add: connection-status UI, viewer count, `assets.small_image`, join/spectate secrets, party fields, reconnect logic, offline/"was live" presence, a dockable panel.

**Reference:** the design spec is `docs/superpowers/specs/2026-09-03-obs-discord-rpc-plugin-design.md`. Read it before starting.

---

## Task 1: RakuSpace `/api/check` returns the stream title

**Files:**
- Modify: `frontend/RakuSpace.py` (the `check_stream` route, currently lines 793–799)
- Modify: `frontend/tests/test_rakuspace.py` (two existing assertions at ~lines 161–174)

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `GET /api/check/<streamname>` response JSON shape `{"known": <bool>, "title": <string|null>}`. Task 6's go-live fetch and the Verify button (Task 5) rely on exactly these two keys. `title` is the user's `stream_title` column value, which may be `null` or an empty string.

- [ ] **Step 1: Update the two existing tests to expect the new key**

In `frontend/tests/test_rakuspace.py`, change `test_api_check_unknown_stream`:

```python
def test_api_check_unknown_stream(client):
    resp = client.get("/api/check/nobody")
    assert resp.status_code == 200
    assert resp.get_json() == {"known": False, "title": None}
```

and `test_api_check_known_stream`:

```python
def test_api_check_known_stream(client, db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO users (username, streamkey) VALUES ('alice', 'k')")
    conn.commit()
    conn.close()

    resp = client.get("/api/check/alice")
    assert resp.get_json() == {"known": True, "title": None}
```

- [ ] **Step 2: Add a test for the title being returned when set**

Add directly below `test_api_check_known_stream`:

```python
def test_api_check_returns_stream_title(client, db_path):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO users (username, streamkey, stream_title) VALUES ('bob', 'k', 'Perfect Dark 100%')"
    )
    conn.commit()
    conn.close()

    resp = client.get("/api/check/bob")
    assert resp.get_json() == {"known": True, "title": "Perfect Dark 100%"}
```

- [ ] **Step 3: Run the tests to verify they fail**

Run (from `frontend/`, inside the venv):

```bash
python -m pytest tests/test_rakuspace.py::test_api_check_unknown_stream tests/test_rakuspace.py::test_api_check_known_stream tests/test_rakuspace.py::test_api_check_returns_stream_title -v
```

Expected: all three FAIL — the two updated ones on the assertion (`{'known': False}` != `{'known': False, 'title': None}`), the new one likewise.

- [ ] **Step 4: Implement the route change**

In `frontend/RakuSpace.py`, replace the `check_stream` function body:

```python
@app.route("/api/check/<streamname>")
def check_stream(streamname):
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT stream_title FROM users WHERE username=?", (streamname,))
    row = cur.fetchone()
    title = row["stream_title"] if row is not None else None
    return jsonify({"known": row is not None, "title": title})
```

- [ ] **Step 5: Run the tests to verify they pass**

Run:

```bash
python -m pytest tests/test_rakuspace.py -v
```

Expected: the three targeted tests PASS and the rest of the file is still green.

- [ ] **Step 6: Commit**

```bash
git add frontend/RakuSpace.py frontend/tests/test_rakuspace.py
git commit -m "Return stream_title from /api/check for the OBS plugin"
```

---

## Task 2: Scaffold the `obs-plugin/` tree from the template

**Files:**
- Create: `obs-plugin/` (whole tree, from `obsproject/obs-plugin-template`)
- Create: `obs-plugin/src/rakuspace-config.h`
- Modify (within the copied template): `buildspec.json`, `CMakeLists.txt`, `.github/workflows/*`, `cmake/` presets, `src/plugin-main.c` → `src/plugin-main.cpp`
- Create: `obs-plugin/src/vendor/nlohmann/json.hpp` (vendored single header)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - A configurable, buildable (on Linux) empty OBS plugin named `rakuspace-obs`.
  - `obs-plugin/src/rakuspace-config.h` defining, as C string macros:
    - `RAKUSPACE_RTMP_INGEST` — e.g. `"rtmp://park.raku.party:1935/live"` (confirm exact host/port/app-name against the running deployment; see design spec §"Component 1")
    - `RAKUSPACE_SITE_BASE` — `"https://rakuspace.site"` (no trailing slash)
    - `RAKUSPACE_DISCORD_APP_ID` — the real Application ID from Step 2 below
  - `#include "vendor/nlohmann/json.hpp"` is available to all `src/` files.
  - CMake presets: a Linux preset and a `windows-x64` preset only.

- [ ] **Step 1: Copy the template into `obs-plugin/`**

```bash
cd /home/glizzy/Projects/rakuspace
git clone --depth=1 https://github.com/obsproject/obs-plugin-template /tmp/obs-plugin-template
mkdir obs-plugin
cp -r /tmp/obs-plugin-template/. obs-plugin/
rm -rf obs-plugin/.git
```

Read `obs-plugin/README.md` and `obs-plugin/buildspec.json` — the template's exact layout evolves; the edits below are described by intent, adapt field names to what the current template uses.

- [ ] **Step 2: Create the Discord Application and record its ID**

In a browser: Discord Developer Portal → **New Application**, name **"RakuSpace"** → **Rich Presence → Art Assets** → upload the RakuSpace logo with asset key `logo` → copy the **Application ID**. No OAuth redirect URIs, no scopes, no bot user, no review submission.

- [ ] **Step 3: Write `obs-plugin/src/rakuspace-config.h`**

```c
#pragma once

/*
 * Deployment-specific constants. These are the only values to change when
 * pointing this plugin at a different RakuSpace / OME deployment.
 */

/* RTMP ingest: scheme + host + port + OME app name, no trailing slash.
 * Must match what /stream_info shows as the "RTMP URL". */
#define RAKUSPACE_RTMP_INGEST "rtmp://park.raku.party:1935/live"

/* Public site base, no trailing slash. Used for /api/check and /live links. */
#define RAKUSPACE_SITE_BASE "https://rakuspace.site"

/* Discord Application ID from the Developer Portal (Rich Presence). */
#define RAKUSPACE_DISCORD_APP_ID "PASTE_REAL_ID_FROM_STEP_2"
```

Replace `park.raku.party:1935/live` with the confirmed real ingest and `PASTE_REAL_ID_FROM_STEP_2` with the real ID.

- [ ] **Step 4: Rename the plugin and set metadata**

- In `buildspec.json`: set the plugin `name` to `rakuspace-obs`, `displayName` to `RakuSpace`, `version` to `1.0.0`, author/website to the project's.
- In `CMakeLists.txt`: set the project name to `rakuspace-obs` (or wherever the template takes the name — often it reads `buildspec.json`).
- Rename `src/plugin-main.c` to `src/plugin-main.cpp`. Update any `CMakeLists.txt` / `cmake/` source list that names it. Ensure the target is compiled as C++17 (`set(CMAKE_CXX_STANDARD 17)` / `target_compile_features(... cxx_std_17)`).

- [ ] **Step 5: Strip macOS, keep Linux + Windows**

- Delete macOS presets from `CMakePresets.json` (keep the Linux one — `ubuntu-x86_64` or `linux-x86_64`, check `cmake --list-presets` — and `windows-x64`).
- In `.github/workflows/` (e.g. `build-project.yaml`): remove the `macos` matrix entries / jobs. Keep Windows (release artifact) and Linux (compile-check). Leave `check-format` jobs alone if present.
- Remove `cmake/macos/` if present.

- [ ] **Step 6: Vendor `nlohmann/json`**

```bash
mkdir -p obs-plugin/src/vendor/nlohmann
curl -L -o obs-plugin/src/vendor/nlohmann/json.hpp \
  https://github.com/nlohmann/json/releases/latest/download/json.hpp
```

Add `obs-plugin/src` to the target's include directories in `CMakeLists.txt` if not already (so `#include "vendor/nlohmann/json.hpp"` resolves).

- [ ] **Step 7: Add libcurl to the build**

In `CMakeLists.txt`, after the obs target is defined:

```cmake
find_package(CURL REQUIRED)
target_link_libraries(${CMAKE_PROJECT_NAME} PRIVATE CURL::libcurl)
```

If the Windows configure step cannot find CURL, add `"curl"` to the `dependencies` list in `buildspec.json` (OBS's obs-deps ships a prebuilt curl).

- [ ] **Step 8: Make `plugin-main.cpp` a minimal valid module**

Replace `src/plugin-main.cpp` with:

```cpp
#include <obs-module.h>

OBS_DECLARE_MODULE()
OBS_MODULE_USE_DEFAULT_LOCALE("rakuspace-obs", "en-US")

MODULE_EXPORT const char *obs_module_description(void)
{
	return "RakuSpace streaming service and Discord Rich Presence";
}

bool obs_module_load(void)
{
	blog(LOG_INFO, "[rakuspace-obs] loaded");
	return true;
}

void obs_module_unload(void)
{
	blog(LOG_INFO, "[rakuspace-obs] unloaded");
}
```

- [ ] **Step 9: Configure and build on Linux**

```bash
cd obs-plugin
cmake --preset ubuntu-x86_64   # or linux-x86_64 — whatever `cmake --list-presets` shows
cmake --build --preset ubuntu-x86_64
```

Expected: configure succeeds (finds libobs + CURL), build produces `rakuspace-obs.so` (path under `build_x86_64/` or similar) with no errors.

- [ ] **Step 10: Commit**

```bash
cd /home/glizzy/Projects/rakuspace
git add obs-plugin
git commit -m "Scaffold obs-plugin from obs-plugin-template (Linux+Windows only)"
```

---

## Task 3: Discord IPC client (`discord-rpc`)

**Files:**
- Create: `obs-plugin/src/discord-rpc.hpp`
- Create: `obs-plugin/src/discord-rpc.cpp`
- Create: `obs-plugin/src/tools/rpc-smoke.cpp` (opt-in manual test binary)
- Modify: `obs-plugin/CMakeLists.txt` (add the two source files to the target; add the opt-in smoke target)

**Interfaces:**
- Consumes: `RAKUSPACE_DISCORD_APP_ID` from `rakuspace-config.h`; `vendor/nlohmann/json.hpp`.
- Produces (used by Task 6):

```cpp
namespace rakuspace {

struct Activity {
	std::string details;       // required, card line 1
	std::string state;         // card line 2; empty => omitted
	int64_t     start_ts = 0;  // epoch seconds; 0 => omitted
	std::string large_image;   // asset key, e.g. "logo"
	std::string large_text;    // e.g. "RakuSpace"
	std::string button_label;  // e.g. "Watch Stream"
	std::string button_url;    // https URL
};

class DiscordRpc {
public:
	static DiscordRpc &instance();
	bool connect();                       // find + open pipe, handshake. false if Discord absent.
	bool set_activity(const Activity &);  // false if not connected / write failed
	bool clear();                         // set activity to null
	void close();
	bool connected() const;
private:
	// platform-specific handle, not exposed
};

} // namespace rakuspace
```

All methods are safe to call when Discord is not running: `connect()` returns `false`, the rest become no-ops. No exceptions escape.

- [ ] **Step 1: Write `discord-rpc.hpp`**

Exactly the interface block above, wrapped in `#pragma once` and the needed `#include <string>` / `<cstdint>`.

- [ ] **Step 2: Write `discord-rpc.cpp`**

```cpp
#include "discord-rpc.hpp"
#include "rakuspace-config.h"
#include "vendor/nlohmann/json.hpp"

#include <atomic>
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
		ssize_t wrote = ::write(p.fd, buf, len);
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
	bool ready = false;
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
	drain_frame(impl_->pipe); // ack; ignore contents
	return true;
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
	drain_frame(impl_->pipe);
	return true;
}

void DiscordRpc::close()
{
	std::lock_guard<std::mutex> lk(impl_->mtx);
	impl_->pipe.reset();
	impl_->ready = false;
}

} // namespace rakuspace
```

Add the matching private members to `discord-rpc.hpp`: a `struct Impl; Impl *impl_;`, a private constructor/destructor declaration, and `DiscordRpc(const DiscordRpc&) = delete;`.

- [ ] **Step 3: Write the opt-in smoke binary `src/tools/rpc-smoke.cpp`**

```cpp
// Manual check: with Discord desktop running, build with -DRAKUSPACE_BUILD_SMOKE=ON
// and run ./rpc-smoke — a "Live on RakuSpace" card should appear on your profile
// for ~10 seconds, then clear.
#include "../discord-rpc.hpp"
#include <chrono>
#include <cstdio>
#include <ctime>
#include <thread>

int main()
{
	auto &rpc = rakuspace::DiscordRpc::instance();
	if (!rpc.connect()) {
		std::puts("connect failed (is Discord running?)");
		return 1;
	}
	rakuspace::Activity a;
	a.details = "Live on RakuSpace";
	a.state = "Perfect Dark 100% run";
	a.start_ts = (int64_t)::time(nullptr);
	a.large_image = "logo";
	a.large_text = "RakuSpace";
	a.button_label = "Watch Stream";
	a.button_url = "https://rakuspace.site/live/example";
	std::printf("set_activity: %d\n", (int)rpc.set_activity(a));
	std::this_thread::sleep_for(std::chrono::seconds(10));
	rpc.clear();
	rpc.close();
	return 0;
}
```

- [ ] **Step 4: Wire the sources into CMake**

In `obs-plugin/CMakeLists.txt`, add `src/discord-rpc.cpp` to the plugin target's source list. Then append:

```cmake
option(RAKUSPACE_BUILD_SMOKE "Build the standalone Discord RPC smoke test" OFF)
if(RAKUSPACE_BUILD_SMOKE)
  add_executable(rpc-smoke src/tools/rpc-smoke.cpp src/discord-rpc.cpp)
  target_include_directories(rpc-smoke PRIVATE src)
  target_compile_features(rpc-smoke PRIVATE cxx_std_17)
endif()
```

- [ ] **Step 5: Build the plugin (compile-check)**

```bash
cd obs-plugin
cmake --preset ubuntu-x86_64
cmake --build --preset ubuntu-x86_64
```

Expected: clean build, `discord-rpc.cpp` compiles into the module.

- [ ] **Step 6: Build and run the smoke test — manual matrix**

```bash
cmake -S . -B build-smoke -DRAKUSPACE_BUILD_SMOKE=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build-smoke --target rpc-smoke
./build-smoke/rpc-smoke     # Discord desktop must be running and logged in
```

Expected with Discord running: prints `set_activity: 1`; a card titled **Live on RakuSpace** with a second line **Perfect Dark 100% run**, an elapsed timer, the RakuSpace logo, and a **Watch Stream** button appears on your Discord profile for ~10s, then disappears.
Expected with Discord NOT running: prints `connect failed (is Discord running?)`, exits 1, no crash.

- [ ] **Step 7: Commit**

```bash
cd /home/glizzy/Projects/rakuspace
git add obs-plugin
git commit -m "Add minimal Discord IPC client (discord-rpc)"
```

---

## Task 4: Register the "RakuSpace" streaming service

**Files:**
- Create: `obs-plugin/src/rakuspace-service.hpp`
- Create: `obs-plugin/src/rakuspace-service.cpp`
- Create/append: `obs-plugin/data/locale/en-US.ini`
- Modify: `obs-plugin/src/plugin-main.cpp` (register the service on load)
- Modify: `obs-plugin/CMakeLists.txt` (add `src/rakuspace-service.cpp`)

**Interfaces:**
- Consumes: `RAKUSPACE_RTMP_INGEST` from `rakuspace-config.h`.
- Produces (used by Tasks 5 and 6):
  - Service type id string: `"rakuspace_service"`.
  - `void rakuspace_register_service(void);` declared in `rakuspace-service.hpp`, called from `obs_module_load`.
  - Service settings keys, all read via `obs_data_get_*` on `obs_service_get_settings()`:
    - `"username"` — string
    - `"stream_key"` — string
    - `"discord_enabled"` — bool (default false)
    - `"discord_include_title"` — bool (default false)
    - `"discord_status_text"` — string (default `"Live on RakuSpace"`)

- [ ] **Step 1: Add locale strings**

Append to `obs-plugin/data/locale/en-US.ini`:

```ini
RakuSpace.Service.Name="RakuSpace"
RakuSpace.Prop.Username="RakuSpace username"
RakuSpace.Prop.Username.Tip="Your RakuSpace login name. Used only for the Discord link and title check — not for stream authentication."
RakuSpace.Prop.StreamKey="Stream key"
RakuSpace.Prop.StreamKey.Tip="Copy the 'Stream Key' value from your RakuSpace stream_info page (looks like 12_abcdef...)."
RakuSpace.Prop.Verify="Verify username"
RakuSpace.Prop.VerifyIdle="Not checked yet."
RakuSpace.Prop.VerifyOk="Found — link will work."
RakuSpace.Prop.VerifyBad="Not found — check the spelling."
RakuSpace.Prop.VerifyErr="Could not reach RakuSpace."
RakuSpace.Prop.DiscordEnabled="Share status to Discord"
RakuSpace.Prop.DiscordTitle="Include stream title in the card"
RakuSpace.Prop.DiscordStatusText="Status text"
```

- [ ] **Step 2: Write `rakuspace-service.hpp`**

```cpp
#pragma once

#define RAKUSPACE_SERVICE_ID "rakuspace_service"

void rakuspace_register_service(void);
```

- [ ] **Step 3: Write `rakuspace-service.cpp` — skeleton, name, defaults, connect info**

```cpp
#include "rakuspace-service.hpp"
#include "rakuspace-config.h"

#include <obs-module.h>
#include <string>

struct rakuspace_service {
	std::string username;
	std::string stream_key;
};

static const char *rs_name(void *)
{
	return obs_module_text("RakuSpace.Service.Name");
}

static void *rs_create(obs_data_t *settings, obs_service_t *)
{
	auto *s = new rakuspace_service();
	s->username = obs_data_get_string(settings, "username");
	s->stream_key = obs_data_get_string(settings, "stream_key");
	return s;
}

static void rs_destroy(void *data)
{
	delete static_cast<rakuspace_service *>(data);
}

static void rs_update(void *data, obs_data_t *settings)
{
	auto *s = static_cast<rakuspace_service *>(data);
	s->username = obs_data_get_string(settings, "username");
	s->stream_key = obs_data_get_string(settings, "stream_key");
}

static void rs_defaults(obs_data_t *defaults)
{
	obs_data_set_default_bool(defaults, "discord_enabled", false);
	obs_data_set_default_bool(defaults, "discord_include_title", false);
	obs_data_set_default_string(defaults, "discord_status_text", "Live on RakuSpace");
}

static const char *rs_connect_info(void *data, uint32_t type)
{
	auto *s = static_cast<rakuspace_service *>(data);
	switch (type) {
	case OBS_SERVICE_CONNECT_INFO_SERVER_URL:
		return RAKUSPACE_RTMP_INGEST;
	case OBS_SERVICE_CONNECT_INFO_STREAM_KEY:
		return s->stream_key.c_str();
	default:
		return nullptr;
	}
}

static const char *rs_protocol(void *)
{
	return "RTMP";
}

static bool rs_can_connect(void *data, uint32_t protocols)
{
	UNUSED_PARAMETER(protocols);
	auto *s = static_cast<rakuspace_service *>(data);
	return !s->stream_key.empty();
}
```

Note: `OBS_SERVICE_CONNECT_INFO_*` enum values and the exact `get_connect_info` signature are in `<obs-service.h>` (OBS ≥ 30.1). If a `can_try_to_connect` field name differs in the installed headers, match the header.

- [ ] **Step 4: Add the properties panel (in the same file)**

```cpp
static bool discord_toggled(obs_properties_t *props, obs_property_t *,
			    obs_data_t *settings)
{
	bool on = obs_data_get_bool(settings, "discord_enabled");
	obs_property_set_enabled(obs_properties_get(props, "discord_include_title"), on);
	obs_property_set_enabled(obs_properties_get(props, "discord_status_text"), on);
	return true;
}

// Forward-declared; implemented in Task 5.
bool rakuspace_verify_button(obs_properties_t *props, obs_property_t *property,
			     void *data);

static obs_properties_t *rs_properties(void *)
{
	obs_properties_t *p = obs_properties_create();

	obs_property_t *user = obs_properties_add_text(
		p, "username", obs_module_text("RakuSpace.Prop.Username"), OBS_TEXT_DEFAULT);
	obs_property_set_long_description(user, obs_module_text("RakuSpace.Prop.Username.Tip"));

	obs_property_t *key = obs_properties_add_text(
		p, "stream_key", obs_module_text("RakuSpace.Prop.StreamKey"), OBS_TEXT_PASSWORD);
	obs_property_set_long_description(key, obs_module_text("RakuSpace.Prop.StreamKey.Tip"));

	obs_properties_add_button2(p, "verify_btn",
				  obs_module_text("RakuSpace.Prop.Verify"),
				  rakuspace_verify_button, nullptr);
	obs_property_t *verdict = obs_properties_add_text(
		p, "verify_result", obs_module_text("RakuSpace.Prop.VerifyIdle"), OBS_TEXT_INFO);
	UNUSED_PARAMETER(verdict);

	obs_property_t *den = obs_properties_add_bool(
		p, "discord_enabled", obs_module_text("RakuSpace.Prop.DiscordEnabled"));
	obs_property_set_modified_callback(den, discord_toggled);

	obs_properties_add_bool(p, "discord_include_title",
				obs_module_text("RakuSpace.Prop.DiscordTitle"));
	obs_properties_add_text(p, "discord_status_text",
				obs_module_text("RakuSpace.Prop.DiscordStatusText"),
				OBS_TEXT_DEFAULT);

	// Apply initial enabled-state from current settings.
	obs_data_t *cur = obs_service_get_settings(
		/* no service ptr here; OBS calls rs_properties with data=service private,
		   so instead rely on discord_toggled firing on first open. */
		nullptr);
	UNUSED_PARAMETER(cur);

	return p;
}
```

If `obs_properties_add_button2` is unavailable in the installed headers, use `obs_properties_add_button` with a `obs_property_clicked_t` callback of signature `bool(obs_properties_t*, obs_property_t*)` and reach the settings via a file-static pointer set in `rs_update`. Prefer `button2`.

For the initial enabled state: the simplest correct approach is to leave both sub-properties enabled by default in `rs_properties` and let `discord_toggled` correct them the moment the checkbox is touched; OBS also invokes modified callbacks on dialog open in current versions. Do not call `obs_service_get_settings(nullptr)` — delete that block; it was illustrative of the wrong path.

- [ ] **Step 5: Define the `obs_service_info` and the register function (end of file)**

```cpp
static struct obs_service_info rakuspace_service_info = {};

void rakuspace_register_service(void)
{
	rakuspace_service_info.id = RAKUSPACE_SERVICE_ID;
	rakuspace_service_info.get_name = rs_name;
	rakuspace_service_info.create = rs_create;
	rakuspace_service_info.destroy = rs_destroy;
	rakuspace_service_info.update = rs_update;
	rakuspace_service_info.get_defaults = rs_defaults;
	rakuspace_service_info.get_properties = rs_properties;
	rakuspace_service_info.get_connect_info = rs_connect_info;
	rakuspace_service_info.get_protocol = rs_protocol;
	rakuspace_service_info.can_try_to_connect = rs_can_connect;
	// NOT setting .flags = OBS_SERVICE_INTERNAL — must be user-visible.

	obs_register_service(&rakuspace_service_info);
}
```

Match field names to the installed `<obs-service.h>`. If `get_defaults` there is `get_defaults2`, adapt.

- [ ] **Step 6: Call it from `obs_module_load`**

In `src/plugin-main.cpp`:

```cpp
#include "rakuspace-service.hpp"
// ...
bool obs_module_load(void)
{
	rakuspace_register_service();
	blog(LOG_INFO, "[rakuspace-obs] loaded");
	return true;
}
```

- [ ] **Step 7: Add to CMake and build**

Add `src/rakuspace-service.cpp` to the target source list. Then:

```bash
cd obs-plugin
cmake --preset ubuntu-x86_64 && cmake --build --preset ubuntu-x86_64
```

Expected: clean build.

- [ ] **Step 8: Install into OBS and test — manual matrix items 1 & 2**

Copy the built `.so`/`.dll` into the OBS plugin path for the dev machine (Linux: `~/.config/obs-studio/plugins/rakuspace-obs/bin/64bit/`, or use `cmake --build --preset ... --target install` if the template wires it). Restart OBS.

1. Settings → Stream → Service dropdown: **RakuSpace** is listed (possibly under "Show all"). Select it. The panel shows: RakuSpace username, Stream key (masked), Verify username button + result line, Share status to Discord (off), and — greyed until the box is ticked — Include stream title + Status text (prefilled "Live on RakuSpace"). Enter a real username + real `<userid>_<streamkey>` from `/stream_info`, click Start Streaming: OBS connects, and the stream plays back at `https://rakuspace.site/live/<username>`.
2. Switch the Service dropdown to **Custom…**, set Server = the RTMP URL and Stream Key = `<userid>_<streamkey>` as before: streaming still works. (Escape hatch intact.)

- [ ] **Step 9: Commit**

```bash
cd /home/glizzy/Projects/rakuspace
git add obs-plugin
git commit -m "Register the RakuSpace streaming service with its properties panel"
```

---

## Task 5: Verify-username button + go-live glue + activity payload

**Files:**
- Create: `obs-plugin/src/rakuspace-http.hpp`
- Create: `obs-plugin/src/rakuspace-http.cpp`
- Modify: `obs-plugin/src/plugin-main.cpp` (frontend event callback; the verify button)
- Modify: `obs-plugin/CMakeLists.txt` (add `src/rakuspace-http.cpp`)

**Interfaces:**
- Consumes:
  - `RAKUSPACE_SITE_BASE` from `rakuspace-config.h`.
  - `RAKUSPACE_SERVICE_ID`, the settings keys, from `rakuspace-service.hpp` / Task 4.
  - `rakuspace::DiscordRpc`, `rakuspace::Activity` from `discord-rpc.hpp` / Task 3.
  - `GET /api/check/<streamname>` → `{"known": bool, "title": string|null}` from Task 1.
- Produces:
  - `rakuspace-http.hpp`:

```cpp
#pragma once
#include <string>

namespace rakuspace {

struct CheckResult {
	bool reached = false;   // HTTP round-trip completed
	bool known = false;     // "known" field
	std::string title;      // "title" field ("" if null/absent)
};

std::string url_encode(const std::string &s);
// Blocking GET with a 3s total timeout. Never throws.
CheckResult check_user(const std::string &username);

} // namespace rakuspace
```

- [ ] **Step 1: Write `rakuspace-http.cpp`**

```cpp
#include "rakuspace-http.hpp"
#include "rakuspace-config.h"
#include "vendor/nlohmann/json.hpp"

#include <curl/curl.h>
#include <cctype>
#include <cstdio>

using json = nlohmann::json;

namespace rakuspace {

std::string url_encode(const std::string &s)
{
	static const char *hex = "0123456789ABCDEF";
	std::string out;
	for (unsigned char c : s) {
		if (std::isalnum(c) || c == '-' || c == '_' || c == '.' || c == '~') {
			out.push_back((char)c);
		} else {
			out.push_back('%');
			out.push_back(hex[c >> 4]);
			out.push_back(hex[c & 0xF]);
		}
	}
	return out;
}

static size_t write_cb(char *ptr, size_t size, size_t nmemb, void *userdata)
{
	auto *buf = static_cast<std::string *>(userdata);
	size_t n = size * nmemb;
	if (buf->size() + n > 64 * 1024) // sanity cap
		return 0;
	buf->append(ptr, n);
	return n;
}

CheckResult check_user(const std::string &username)
{
	CheckResult r;
	CURL *curl = curl_easy_init();
	if (!curl)
		return r;

	std::string url = std::string(RAKUSPACE_SITE_BASE) + "/api/check/" + url_encode(username);
	std::string body;

	curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
	curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_cb);
	curl_easy_setopt(curl, CURLOPT_WRITEDATA, &body);
	curl_easy_setopt(curl, CURLOPT_TIMEOUT_MS, 3000L);
	curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT_MS, 3000L);
	curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
	curl_easy_setopt(curl, CURLOPT_USERAGENT, "rakuspace-obs/1.0");

	CURLcode rc = curl_easy_perform(curl);
	long status = 0;
	curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &status);
	curl_easy_cleanup(curl);

	if (rc != CURLE_OK || status != 200)
		return r;
	r.reached = true;

	try {
		json j = json::parse(body);
		r.known = j.value("known", false);
		if (j.contains("title") && j["title"].is_string())
			r.title = j["title"].get<std::string>();
	} catch (...) {
		r.reached = false;
	}
	return r;
}

} // namespace rakuspace
```

- [ ] **Step 2: Implement the verify button in `plugin-main.cpp`**

```cpp
#include "rakuspace-service.hpp"
#include "rakuspace-http.hpp"
#include "discord-rpc.hpp"
#include <obs-frontend-api.h>
#include <obs-module.h>
#include <atomic>
#include <ctime>
#include <string>
#include <thread>

bool rakuspace_verify_button(obs_properties_t *props, obs_property_t *,
			     void *)
{
	obs_service_t *svc = obs_frontend_get_streaming_service();
	std::string username;
	if (svc) {
		obs_data_t *s = obs_service_get_settings(svc);
		username = obs_data_get_string(s, "username");
		obs_data_release(s);
	}

	obs_property_t *result = obs_properties_get(props, "verify_result");
	if (username.empty()) {
		obs_property_set_description(result, obs_module_text("RakuSpace.Prop.VerifyBad"));
		return true;
	}

	rakuspace::CheckResult cr = rakuspace::check_user(username);
	const char *msg;
	if (!cr.reached)
		msg = obs_module_text("RakuSpace.Prop.VerifyErr");
	else if (cr.known)
		msg = obs_module_text("RakuSpace.Prop.VerifyOk");
	else
		msg = obs_module_text("RakuSpace.Prop.VerifyBad");
	obs_property_set_description(result, msg);
	return true; // refresh the properties view
}
```

Note: `obs_frontend_get_streaming_service()` returns the service currently configured in Settings → Stream, which is what the panel is editing — acceptable for a user-initiated button. The 3s blocking call on the UI thread is acceptable here (single click, bounded).

- [ ] **Step 3: Implement the frontend event callback in `plugin-main.cpp`**

```cpp
static std::atomic<uint64_t> g_stream_generation{0};

static void build_and_push_activity(uint64_t generation, std::string username,
				    bool include_title, std::string status_text,
				    int64_t start_ts)
{
	std::string state;
	if (include_title) {
		rakuspace::CheckResult cr = rakuspace::check_user(username);
		if (cr.reached && !cr.known)
			return; // username invalid -> skip Discord entirely
		if (cr.reached && !cr.title.empty())
			state = cr.title;
	}

	if (generation != g_stream_generation.load())
		return; // stream already stopped

	rakuspace::Activity a;
	a.details = status_text.empty() ? "Live on RakuSpace" : status_text;
	a.state = state;
	a.start_ts = start_ts;
	a.large_image = "logo";
	a.large_text = "RakuSpace";
	a.button_label = "Watch Stream";
	a.button_url = std::string(RAKUSPACE_SITE_BASE) + "/live/" + username;

	auto &rpc = rakuspace::DiscordRpc::instance();
	if (rpc.connect() && generation == g_stream_generation.load())
		rpc.set_activity(a);
}

static void on_frontend_event(enum obs_frontend_event event, void *)
{
	if (event == OBS_FRONTEND_EVENT_STREAMING_STARTED) {
		obs_service_t *svc = obs_frontend_get_streaming_service();
		if (!svc)
			return;
		const char *type = obs_service_get_type(svc);
		if (!type || std::string(type) != RAKUSPACE_SERVICE_ID)
			return;

		obs_data_t *s = obs_service_get_settings(svc);
		bool enabled = obs_data_get_bool(s, "discord_enabled");
		std::string username = obs_data_get_string(s, "username");
		bool include_title = obs_data_get_bool(s, "discord_include_title");
		std::string status_text = obs_data_get_string(s, "discord_status_text");
		obs_data_release(s);

		if (!enabled || username.empty())
			return;

		uint64_t gen = ++g_stream_generation;
		int64_t start_ts = (int64_t)::time(nullptr);
		std::thread(build_and_push_activity, gen, username, include_title,
			    status_text, start_ts)
			.detach();

	} else if (event == OBS_FRONTEND_EVENT_STREAMING_STOPPED) {
		++g_stream_generation; // invalidate any in-flight build
		auto &rpc = rakuspace::DiscordRpc::instance();
		rpc.clear();
		rpc.close();
	}
}
```

- [ ] **Step 4: Register the callback and curl global init in `obs_module_load`**

```cpp
#include <curl/curl.h>

bool obs_module_load(void)
{
	curl_global_init(CURL_GLOBAL_DEFAULT);
	rakuspace_register_service();
	obs_frontend_add_event_callback(on_frontend_event, nullptr);
	blog(LOG_INFO, "[rakuspace-obs] loaded");
	return true;
}

void obs_module_unload(void)
{
	obs_frontend_remove_event_callback(on_frontend_event, nullptr);
	rakuspace::DiscordRpc::instance().close();
	curl_global_cleanup();
	blog(LOG_INFO, "[rakuspace-obs] unloaded");
}
```

- [ ] **Step 5: Add to CMake and build**

Add `src/rakuspace-http.cpp` to the target source list. Then:

```bash
cd obs-plugin
cmake --preset ubuntu-x86_64 && cmake --build --preset ubuntu-x86_64
```

Expected: clean build.

- [ ] **Step 6: Install into OBS and run manual matrix items 3–8**

Reinstall the built module, restart OBS, select the RakuSpace service.

3. `discord_enabled` off → Start/Stop streaming: no Discord activity ever appears (with Discord running).
4. `discord_enabled` on, Discord desktop running → Start Streaming: card appears with `details` = status text and the `Watch Stream` button URL = `https://rakuspace.site/live/<username>`; Stop Streaming → card clears.
5. `discord_enabled` on, Discord desktop NOT running → Start Streaming: stream is unaffected, no error dialog, OBS log shows no crash.
6. `discord_include_title` on: (a) user with a stream title → line 2 shows the title; (b) user with no title → single-line card; (c) block `rakuspace.site` in `/etc/hosts` to force a timeout → single-line card within ~3s, stream unaffected.
7. `discord_include_title` on, username that does not exist → no card appears, stream still goes live.
8. Verify username button: real username → "Found — link will work."; bogus username → "Not found — check the spelling."; `rakuspace.site` unreachable → "Could not reach RakuSpace." None block editing or streaming.

- [ ] **Step 7: Commit**

```bash
cd /home/glizzy/Projects/rakuspace
git add obs-plugin
git commit -m "Wire go-live Discord presence and the verify-username button"
```

---

## Task 6: CI trim, README, and full release verification

**Files:**
- Modify: `obs-plugin/.github/workflows/*` (final trim + sanity)
- Create: `obs-plugin/README.md`
- Modify: `README.md` (top-level — one line pointing at `obs-plugin/`)

**Interfaces:**
- Consumes: everything above.
- Produces: a documented, CI-built plugin.

- [ ] **Step 1: Finalize CI**

In `obs-plugin/.github/workflows/` ensure:
- The build workflow matrix has only `windows` (produces the release artifact / installer) and `ubuntu` (compile-check, no artifact needed).
- No `macos` jobs remain anywhere (`grep -ri macos obs-plugin/.github` returns nothing).
- The Windows job uploads the built `.dll` (+ template's packaging) as a workflow artifact.

- [ ] **Step 2: Write `obs-plugin/README.md`**

Include, in prose:
- What it is: adds a "RakuSpace" service to OBS Settings → Stream and an optional Discord Rich Presence card while live. Requires OBS 30.1+.
- Install: download the Windows build from Releases / CI artifacts, run the installer (or unzip into `%ProgramData%\obs-studio\plugins\`), restart OBS.
- Use: Settings → Stream → Service → RakuSpace; paste the Stream Key from your RakuSpace `stream_info` page; type your RakuSpace username; optionally tick "Share status to Discord".
- The three edit points for another deployment, quoting `src/rakuspace-config.h`: `RAKUSPACE_RTMP_INGEST`, `RAKUSPACE_SITE_BASE`, `RAKUSPACE_DISCORD_APP_ID`.
- Discord Application setup (one-time): Developer Portal → New Application "RakuSpace" → Rich Presence → Art Assets → upload logo as key `logo` → copy Application ID into the constant. No OAuth, no scopes, no review.
- Build from source: `cmake --preset windows-x64` / `cmake --preset ubuntu-x86_64`; optional `-DRAKUSPACE_BUILD_SMOKE=ON` for the standalone `rpc-smoke` Discord check.
- Scope note: no connection status, viewer count, reconnect, or offline card by design.

- [ ] **Step 3: Point the top-level README at it**

Add a line under the existing structure description in `/home/glizzy/Projects/rakuspace/README.md` (match its existing style), e.g.:

```
- `obs-plugin/` — OBS Studio plugin: adds a "RakuSpace" streaming service and an optional Discord Rich Presence card while live. See `obs-plugin/README.md`.
```

- [ ] **Step 4: Full manual test matrix on Windows**

On a Windows x64 machine with OBS 30.1+ and Discord desktop:
- Build with `cmake --preset windows-x64 && cmake --build --preset windows-x64` (or install the CI artifact).
- Run all 8 matrix items from Tasks 4–5 again on Windows. Record pass/fail for each in the commit message or a checklist comment.

- [ ] **Step 5: Verify the Flask test suite still passes**

```bash
cd frontend && python -m pytest tests/ -q
```

Expected: all green (Task 1's change plus untouched rest).

- [ ] **Step 6: Commit**

```bash
cd /home/glizzy/Projects/rakuspace
git add obs-plugin README.md
git commit -m "Add obs-plugin README, finalize CI, record release verification"
```

---

## Self-Review

**Spec coverage:**
- Repo layout `obs-plugin/` → Task 2. ✓
- Service registration, `get_connect_info` only, no `OBS_SERVICE_INTERNAL`, baked ingest, Custom escape hatch → Task 4. ✓
- Properties panel (username, stream key, verify button, share checkbox, nested title checkbox, status text, grey-out) → Tasks 4 (fields) + 5 (verify behavior). ✓
- Discord IPC client, single SET_ACTIVITY on go-live + clear on stop, no reconnect, silent no-op when Discord absent → Task 3. ✓
- Card fields (`details`, conditional `state`, `timestamps.start`, `assets.large_image`/`large_text`, single `buttons` entry) → Task 3 `activity_to_json` + Task 5 `build_and_push_activity`. ✓
- Glue: frontend STARTED/STOPPED, service-type check, off-thread fetch, `known:false` → skip, timeout/empty → no state line → Task 5. ✓
- RakuSpace `/api/check` gains `title` → Task 1. ✓
- Baked constants documented as edit points → Task 2 (`rakuspace-config.h`) + Task 6 (README). ✓
- Discord Application setup step → Task 2 Step 2 + Task 6 README. ✓
- Build/CI: template presets, Windows artifact + Linux compile-check, macOS removed → Task 2 (initial) + Task 6 (finalize). ✓
- Manual test matrix (8 items) → Tasks 4 (1–2), 5 (3–8), 6 (full re-run on Windows). ✓
- OBS 30.1 floor → Global Constraints + Task 4 Step 3 note. ✓
- Excluded features not added → none of the tasks introduce them. ✓

**Placeholder scan:** `rakuspace-config.h` intentionally ships with `PASTE_REAL_ID_FROM_STEP_2` and an example ingest host — both are called out as values to replace in the same step, not plan-level TODOs. Task 6 README step is described by required contents, not written out verbatim, because it is prose documentation, not code. No `TBD`/"handle edge cases"/"similar to Task N" left.

**Type consistency:** `DiscordRpc` / `Activity` field names match between `discord-rpc.hpp` (Task 3), `rpc-smoke.cpp` (Task 3), and `build_and_push_activity` (Task 5). `CheckResult` fields (`reached`, `known`, `title`) match between `rakuspace-http.hpp` (Task 5 interface), `rakuspace-http.cpp` (Task 5 Step 1), the verify button (Task 5 Step 2), and `build_and_push_activity` (Task 5 Step 3). Settings keys (`username`, `stream_key`, `discord_enabled`, `discord_include_title`, `discord_status_text`) match between Task 4 defaults/properties and Task 5 reads. Service id `"rakuspace_service"` / `RAKUSPACE_SERVICE_ID` consistent across Tasks 4 and 5. `/api/check` JSON keys (`known`, `title`) consistent between Task 1 and Task 5.

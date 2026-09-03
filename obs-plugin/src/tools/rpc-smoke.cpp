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

/*
RakuSpace OBS plugin
Copyright (C) 2026 RakuSpace <rakubunny@gmail.com>

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License along
with this program. If not, see <https://www.gnu.org/licenses/>
*/

#include <obs-module.h>
#include <obs-frontend-api.h>

#include <curl/curl.h>

#include <atomic>
#include <chrono>
#include <cstdint>
#include <ctime>
#include <string>
#include <thread>

#include "rakuspace-dock.hpp"
#include "rakuspace-config.h"
#include "rakuspace-config-store.hpp"
#include "rakuspace-http.hpp"
#include "rakuspace-output.hpp"
#include "rakuspace-presence.hpp"
#include "discord-rpc.hpp"

OBS_DECLARE_MODULE()
OBS_MODULE_USE_DEFAULT_LOCALE("rakuspace-obs", "en-US")

MODULE_EXPORT const char *obs_module_description(void)
{
	return "RakuSpace dock and Discord Rich Presence";
}

/* ---------------------------------------------------------------------------
 * Go-live glue: push a Discord activity when a RakuSpace stream starts.
 * ------------------------------------------------------------------------- */

static std::atomic<uint64_t> g_stream_generation{0};
static std::atomic<int> g_inflight{0};

struct InflightGuard {
	~InflightGuard() { g_inflight.fetch_sub(1, std::memory_order_relaxed); }
};

static void build_and_push_activity(uint64_t generation, std::string username,
				    bool include_title, std::string status_text,
				    int64_t start_ts)
{
	InflightGuard inflight_guard;

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
	a.button_url = std::string(RAKUSPACE_SITE_BASE) + "/live/" + rakuspace::url_encode(username);

	auto &rpc = rakuspace::DiscordRpc::instance();
	if (generation == g_stream_generation.load() && rpc.connect() &&
	    generation == g_stream_generation.load())
		rpc.set_activity(a);
}

namespace rakuspace {

// Push a Discord activity when our own output goes live. Safe to call from the
// Qt thread: it only spawns a detached worker, it never touches DiscordRpc here.
void presence_on_live()
{
	Config c = load_config();
	if (!c.discord_enabled || c.username.empty())
		return;

	uint64_t gen = ++g_stream_generation;
	g_inflight.fetch_add(1, std::memory_order_relaxed);
	std::thread(build_and_push_activity, gen, c.username, c.discord_include_title,
		    c.discord_status_text, (int64_t)::time(nullptr))
		.detach();
}

// Clear the card when our output stops. Bumps the generation so any in-flight
// push is stale, then does the clear on a detached worker so a wedged Discord
// cannot block the Qt thread. Counted in g_inflight so unload waits for it.
void presence_on_offline()
{
	++g_stream_generation;
	g_inflight.fetch_add(1, std::memory_order_relaxed);
	std::thread([] {
		InflightGuard inflight_guard;
		auto &rpc = rakuspace::DiscordRpc::instance();
		rpc.clear();
		rpc.close();
	}).detach();
}

} // namespace rakuspace

/* ------------------------------------------------------------------------- */

bool obs_module_load(void)
{
	curl_global_init(CURL_GLOBAL_DEFAULT);
	rakuspace::register_dock();
	obs_frontend_add_tools_menu_item("RakuSpace Settings",
					[](void *) { rakuspace::open_settings_dialog(); }, nullptr);
	blog(LOG_INFO, "[rakuspace-obs] loaded");
	return true;
}

void obs_module_unload(void)
{
	rakuspace::DiscordRpc::instance().close();
	rakuspace::OutputManager::instance().shutdown();
	// Let any in-flight go-live fetch finish before tearing down libcurl.
	for (int i = 0; i < 400 && g_inflight.load(std::memory_order_relaxed) > 0; ++i)
		std::this_thread::sleep_for(std::chrono::milliseconds(10));
	curl_global_cleanup();
	blog(LOG_INFO, "[rakuspace-obs] unloaded");
}

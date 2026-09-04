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

#include "rakuspace-service.hpp"
#include "rakuspace-config.h"
#include "rakuspace-http.hpp"
#include "discord-rpc.hpp"

OBS_DECLARE_MODULE()
OBS_MODULE_USE_DEFAULT_LOCALE("rakuspace-obs", "en-US")

MODULE_EXPORT const char *obs_module_description(void)
{
	return "RakuSpace streaming service and Discord Rich Presence";
}

/* ---------------------------------------------------------------------------
 * Verify-username button (wired from rs_properties in rakuspace-service.cpp;
 * forward-declared there, defined here with external linkage).
 * ------------------------------------------------------------------------- */

bool rakuspace_verify_button(obs_properties_t *props, obs_property_t *, void *)
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

/* ---------------------------------------------------------------------------
 * Go-live glue: push a Discord activity when a RakuSpace stream starts.
 * ------------------------------------------------------------------------- */

static std::atomic<uint64_t> g_stream_generation{0};
static std::atomic<int> g_inflight{0};

static void build_and_push_activity(uint64_t generation, std::string username,
				    bool include_title, std::string status_text,
				    int64_t start_ts)
{
	struct InflightGuard {
		~InflightGuard() { g_inflight.fetch_sub(1, std::memory_order_relaxed); }
	} inflight_guard;

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
	if (generation == g_stream_generation.load() && rpc.connect() &&
	    generation == g_stream_generation.load())
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
		g_inflight.fetch_add(1, std::memory_order_relaxed);
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

/* ------------------------------------------------------------------------- */

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
	// Let any in-flight go-live fetch finish before tearing down libcurl.
	for (int i = 0; i < 400 && g_inflight.load(std::memory_order_relaxed) > 0; ++i)
		std::this_thread::sleep_for(std::chrono::milliseconds(10));
	curl_global_cleanup();
	blog(LOG_INFO, "[rakuspace-obs] unloaded");
}

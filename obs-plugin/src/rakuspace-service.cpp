/*
RakuSpace OBS plugin — streaming service registration
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

/* libobs 32.2.2: obs_service_info::can_try_to_connect takes only (void *data);
 * it has no protocols argument (see <obs/obs-service.h> line 106). */
static bool rs_can_connect(void *data)
{
	auto *s = static_cast<rakuspace_service *>(data);
	return !s->stream_key.empty();
}

static bool discord_toggled(obs_properties_t *props, obs_property_t *,
			    obs_data_t *settings)
{
	bool on = obs_data_get_bool(settings, "discord_enabled");
	obs_property_set_enabled(obs_properties_get(props, "discord_include_title"), on);
	obs_property_set_enabled(obs_properties_get(props, "discord_status_text"), on);
	return true;
}

// Forward-declared; real implementation added in Task 5 (moves to plugin-main.cpp).
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

	return p;
}

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
	/* libobs 32.2.2's obs_service_info has no `flags` member, so there is
	 * nothing to clear to keep the service user-visible — it is by default. */

	obs_register_service(&rakuspace_service_info);
}

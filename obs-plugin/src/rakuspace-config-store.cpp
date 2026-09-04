#include "rakuspace-config-store.hpp"

#include "vendor/nlohmann/json.hpp"

#include <obs-module.h>
#include <util/platform.h>

#include <fstream>
#include <sstream>
#include <string>

using json = nlohmann::json;

namespace rakuspace {

static std::string config_path()
{
	char *p = obs_module_config_path("config.json");
	std::string s = p ? p : "";
	bfree(p);
	return s;
}

Config load_config()
{
	Config c;
	std::string path = config_path();
	if (path.empty())
		return c;
	std::ifstream f(path, std::ios::binary);
	if (!f)
		return c;
	std::stringstream ss;
	ss << f.rdbuf();
	try {
		json j = json::parse(ss.str());
		c.stream_key = j.value("stream_key", "");
		c.username = j.value("username", "");
		c.discord_enabled = j.value("discord_enabled", false);
		c.discord_include_title = j.value("discord_include_title", false);
		c.discord_status_text =
			j.value("discord_status_text", std::string("Live on RakuSpace"));
	} catch (...) {
		return Config{};
	}
	return c;
}

bool save_config(const Config &c)
{
	std::string path = config_path();
	if (path.empty())
		return false;

	std::string dir = path;
	size_t slash = dir.find_last_of("/\\");
	if (slash != std::string::npos) {
		dir.resize(slash);
		os_mkdirs(dir.c_str());
	}

	try {
		json j;
		j["stream_key"] = c.stream_key;
		j["username"] = c.username;
		j["discord_enabled"] = c.discord_enabled;
		j["discord_include_title"] = c.discord_include_title;
		j["discord_status_text"] = c.discord_status_text;

		std::ofstream f(path, std::ios::binary | std::ios::trunc);
		if (!f)
			return false;
		f << j.dump(2) << "\n";
		return f.good();
	} catch (...) {
		return false;
	}
}

} // namespace rakuspace

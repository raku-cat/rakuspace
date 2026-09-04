#pragma once
#include <string>

namespace rakuspace {

struct Config {
	std::string stream_key;
	std::string username;
	bool        discord_enabled = false;
	bool        discord_include_title = false;
	std::string discord_status_text = "Live on RakuSpace";
};

// Reads obs_module_config_path("config.json"). Missing or unparseable gives a
// default-constructed Config. Never throws.
Config load_config();

// Writes the file, creating the parent dir. Returns false on a write error.
bool save_config(const Config &c);

}

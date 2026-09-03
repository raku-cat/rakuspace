#pragma once

#include <cstdint>
#include <string>

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
	struct Impl;
	Impl *impl_;

	DiscordRpc();
	~DiscordRpc();
	DiscordRpc(const DiscordRpc &) = delete;
};

} // namespace rakuspace

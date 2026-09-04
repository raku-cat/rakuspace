/*
RakuSpace OBS plugin. Blocking HTTP helper for /api/check.
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
	curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1L);
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

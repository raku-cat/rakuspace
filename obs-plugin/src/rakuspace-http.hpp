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

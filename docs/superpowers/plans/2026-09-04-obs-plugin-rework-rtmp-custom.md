# OBS plugin rework: rtmp_custom handoff instead of a registered service

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Replace the invisible `rakuspace_service` registration with a Tools menu item that points OBS at an `rtmp_custom` service, and repoint the go-live glue at a JSON config store.

**Why:** OBS Settings > Stream only lists `rtmp_common` entries plus Custom. A third-party `obs_service_info` never appears and its callbacks never fire. See spec Revision 1.

**Tech stack:** C++17, libobs + obs-frontend-api (OBS 30.1+), libcurl, vendored `nlohmann/json`. No Qt.

## Global constraints

- No Qt. Menu item via `obs_frontend_add_tools_menu_item` (plain C). Open the config file with `ShellExecuteA` on `_WIN32`, `xdg-open` via `fork`/`exec` or `system` elsewhere.
- Baked constants unchanged in `obs-plugin/src/rakuspace-config.h`: `RAKUSPACE_RTMP_INGEST` (`rtmp://live.rakuspace.on.omusubi.trans:1935/rakuspace`), `RAKUSPACE_SITE_BASE` (`https://rakuspace.apps.raku.party`), `RAKUSPACE_DISCORD_APP_ID` (`1413929830055153898`).
- Config file: `obs_module_config_path("config.json")`. Create the parent dir with `os_mkdirs`. Free the path with `bfree`.
- `rtmp_custom` settings keys: `server`, `key`, `use_auth`. Set `use_auth` to `false` explicitly.
- Service ref rule: `obs_frontend_get_streaming_service()` returns a borrowed pointer, do not release. `obs_frontend_set_streaming_service()` takes its own reference, so release the one from `obs_service_create()` after the set + save. Confirm both against the installed headers/source before relying on it.
- Go-live gate: case-insensitive host compare of the active service `OBS_SERVICE_CONNECT_INFO_SERVER_URL` against the host in `RAKUSPACE_RTMP_INGEST`. Not full-string equality.
- No automated plugin test harness. Implementer verifies with a clean `cmake --preset ubuntu-x86_64` build. Windows/OBS checks are run by the user on the VM.
- All user-facing text and docs: no em dashes, no en dashes, no hyphen as punctuation. Short. Fragments fine. If a line needs a comma or dash to hold together it is too long.
- Keep from the current branch: `discord-rpc.*`, `rakuspace-http.*`, the activity payload, the generation counter, the in-flight guard, `curl_global_*`, the URL-encoded button username.

**Reference:** spec `docs/superpowers/specs/2026-09-03-obs-discord-rpc-plugin-design.md` (read Revision 1 at the end).

Branch: `obs-discord-rpc-plugin`. Current HEAD `114a3dc`.

---

## Task 1: Config store + Tools menu + rtmp_custom handoff

**Files:**
- Delete: `obs-plugin/src/rakuspace-service.cpp`, `obs-plugin/src/rakuspace-service.hpp`
- Create: `obs-plugin/src/rakuspace-setup.cpp`, `obs-plugin/src/rakuspace-setup.hpp`
- Modify: `obs-plugin/src/plugin-main.cpp` (drop `rakuspace_register_service()`, add `rakuspace_register_setup()`)
- Modify: `obs-plugin/CMakeLists.txt` (swap the source file)
- Modify: `obs-plugin/data/locale/en-US.ini` (strip to nothing but keep the file present)

**Interfaces produced (used by Task 2):**

```cpp
// rakuspace-setup.hpp
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

// Reads obs_module_config_path("config.json"). Missing or unparseable -> defaults,
// with `ok` false. Never throws.
Config load_config(bool *ok = nullptr);

void register_setup_menu(void);   // call from obs_module_load
}
```

- [ ] **Step 1: Delete the service unit and its wiring**

Remove `rakuspace-service.cpp` / `.hpp`. In `plugin-main.cpp` remove the `#include "rakuspace-service.hpp"` and the `rakuspace_register_service()` call. In `CMakeLists.txt` remove `src/rakuspace-service.cpp` from the target sources.

- [ ] **Step 2: Write `rakuspace-setup.hpp`**

Exactly the interface block above.

- [ ] **Step 3: Write `rakuspace-setup.cpp` — config load/save**

```cpp
#include "rakuspace-setup.hpp"
#include "rakuspace-config.h"
#include "vendor/nlohmann/json.hpp"

#include <obs-module.h>
#include <obs-frontend-api.h>
#include <util/platform.h>

#include <fstream>
#include <sstream>
#include <string>

#ifdef _WIN32
#include <windows.h>
#include <shellapi.h>
#endif

using json = nlohmann::json;

namespace rakuspace {

static std::string config_file_path()
{
    char *p = obs_module_config_path("config.json");
    std::string s = p ? p : "";
    bfree(p);
    return s;
}

static const char *kTemplate =
    "{\n"
    "  \"stream_key\": \"\",\n"
    "  \"username\": \"\",\n"
    "  \"discord_enabled\": false,\n"
    "  \"discord_include_title\": false,\n"
    "  \"discord_status_text\": \"Live on RakuSpace\"\n"
    "}\n";

Config load_config(bool *ok)
{
    Config c;
    if (ok) *ok = false;
    std::ifstream f(config_file_path(), std::ios::binary);
    if (!f) return c;
    std::stringstream ss;
    ss << f.rdbuf();
    try {
        json j = json::parse(ss.str());
        c.stream_key = j.value("stream_key", "");
        c.username = j.value("username", "");
        c.discord_enabled = j.value("discord_enabled", false);
        c.discord_include_title = j.value("discord_include_title", false);
        c.discord_status_text = j.value("discord_status_text", std::string("Live on RakuSpace"));
        if (ok) *ok = true;
    } catch (...) {
        return Config{};
    }
    return c;
}

static bool write_template_if_missing()
{
    std::string path = config_file_path();
    if (path.empty()) return false;
    if (os_file_exists(path.c_str())) return false;

    // make the parent dir
    std::string dir = path;
    size_t slash = dir.find_last_of("/\\");
    if (slash != std::string::npos) {
        dir.resize(slash);
        os_mkdirs(dir.c_str());
    }
    std::ofstream f(path, std::ios::binary);
    if (!f) return false;
    f << kTemplate;
    return true;
}

static void open_in_editor(const std::string &path)
{
#ifdef _WIN32
    ShellExecuteA(nullptr, "open", path.c_str(), nullptr, nullptr, SW_SHOWNORMAL);
#else
    std::string cmd = "xdg-open \"" + path + "\" &";
    (void)system(cmd.c_str());
#endif
}
```

- [ ] **Step 4: Add the rtmp_custom handoff and the menu callback**

```cpp
static void apply_stream_service(const Config &c)
{
    obs_data_t *settings = obs_data_create();
    obs_data_set_string(settings, "server", RAKUSPACE_RTMP_INGEST);
    obs_data_set_string(settings, "key", c.stream_key.c_str());
    obs_data_set_bool(settings, "use_auth", false);

    obs_service_t *svc = obs_service_create("rtmp_custom", "rakuspace_stream",
                                            settings, nullptr);
    obs_data_release(settings);
    if (!svc) {
        blog(LOG_WARNING, "[rakuspace-obs] obs_service_create(rtmp_custom) failed");
        return;
    }
    obs_frontend_set_streaming_service(svc);  // takes its own ref
    obs_frontend_save_streaming_service();
    obs_service_release(svc);                 // release our create ref
    blog(LOG_INFO, "[rakuspace-obs] stream service set to RakuSpace ingest");
}

static void on_setup_clicked(void *)
{
    std::string path = config_file_path();

    if (write_template_if_missing()) {
        blog(LOG_INFO, "[rakuspace-obs] wrote config template at %s", path.c_str());
        open_in_editor(path);
        return;
    }

    bool ok = false;
    Config c = load_config(&ok);
    if (!ok) {
        blog(LOG_WARNING, "[rakuspace-obs] config.json missing or invalid, reopening");
        open_in_editor(path);
        return;
    }
    if (obs_frontend_streaming_active()) {
        blog(LOG_WARNING, "[rakuspace-obs] stop the stream before applying settings");
        return;
    }
    if (c.stream_key.empty()) {
        blog(LOG_WARNING, "[rakuspace-obs] stream_key is empty in config.json");
        open_in_editor(path);
        return;
    }
    apply_stream_service(c);
    open_in_editor(path);  // let them adjust discord options
}

void register_setup_menu(void)
{
    obs_frontend_add_tools_menu_item("RakuSpace Stream Setup", on_setup_clicked, nullptr);
}

} // namespace rakuspace
```

- [ ] **Step 5: Wire into `plugin-main.cpp`**

```cpp
#include "rakuspace-setup.hpp"
// in obs_module_load(), after curl_global_init:
rakuspace::register_setup_menu();
```

- [ ] **Step 6: CMake + locale**

Add `src/rakuspace-setup.cpp` to the target sources. Reduce `data/locale/en-US.ini` to a single comment line (the file must exist for `OBS_MODULE_USE_DEFAULT_LOCALE`):

```
# no localized strings
```

- [ ] **Step 7: Build**

```
cd obs-plugin && cmake --preset ubuntu-x86_64 && cmake --build --preset ubuntu-x86_64
```

Expected: clean compile + link, no undefined symbols, no warnings.

- [ ] **Step 8: Confirm the header ref semantics claim**

Grep the installed OBS source or docs for `obs_frontend_set_streaming_service` and confirm it takes its own reference (OBS `OBSService` / `OBSRef` assignment addrefs). If the installed source shows otherwise, adjust the release in `apply_stream_service` and note it in the report.

- [ ] **Step 9: Commit**

```
git add -A obs-plugin
git commit -m "Replace service registration with a Tools menu rtmp_custom handoff"
```

**User VM checks (not run by the implementer):**
1. Tools menu shows "RakuSpace Stream Setup". First click creates `config.json` and opens it.
2. Fill `stream_key`, save. Second click. Settings > Stream shows Custom with the ingest URL and the key filled, `use_auth` off.
3. Start Streaming publishes to OME and plays back at `/live/<username>`.
4. Clicking setup while streaming logs a refusal and does not change the service.

---

## Task 2: Repoint the go-live glue, then strings and docs

**Files:**
- Modify: `obs-plugin/src/plugin-main.cpp`
- Modify: `obs-plugin/README.md`
- Modify: `README.md` (top level, the obs-plugin line)
- Modify: PR #6 body on the forge (the controller does this, not a code change)

**Interfaces consumed:** `rakuspace::load_config()` / `rakuspace::Config` from Task 1. `rakuspace::DiscordRpc`, `rakuspace::Activity`, `rakuspace::check_user`, `rakuspace::url_encode` unchanged.

- [ ] **Step 1: Replace the settings read in `STREAMING_STARTED`**

Remove everything that fetched `obs_service_get_settings()` and gated on `RAKUSPACE_SERVICE_ID`. Replace with:

```cpp
if (event == OBS_FRONTEND_EVENT_STREAMING_STARTED) {
    obs_service_t *svc = obs_frontend_get_streaming_service();  // borrowed, no release
    if (!svc) return;

    const char *url = obs_service_get_connect_info(svc, OBS_SERVICE_CONNECT_INFO_SERVER_URL);
    if (!url || !host_matches(url, RAKUSPACE_RTMP_INGEST)) return;

    rakuspace::Config c = rakuspace::load_config();
    if (!c.discord_enabled || c.username.empty()) return;

    uint64_t gen = ++g_stream_generation;
    int64_t start_ts = (int64_t)::time(nullptr);
    g_inflight.fetch_add(1, std::memory_order_relaxed);
    std::thread(build_and_push_activity, gen, c.username, c.discord_include_title,
                c.discord_status_text, start_ts).detach();
}
```

- [ ] **Step 2: Add `host_matches`**

```cpp
// case-insensitive comparison of the host[:port] portion of two rtmp urls
static bool host_matches(const char *a, const char *b)
{
    auto host = [](std::string s) {
        auto p = s.find("://");
        if (p != std::string::npos) s = s.substr(p + 3);
        s = s.substr(0, s.find('/'));
        for (auto &ch : s) ch = (char)tolower((unsigned char)ch);
        return s;
    };
    return host(a) == host(b);
}
```

- [ ] **Step 3: `build_and_push_activity` username validation**

It already calls `check_user` when `include_title` is true and returns on `known == false`. Make that check run regardless of `include_title`:

```cpp
static void build_and_push_activity(uint64_t generation, std::string username,
                                    bool include_title, std::string status_text,
                                    int64_t start_ts)
{
    struct InflightGuard { ~InflightGuard() { g_inflight.fetch_sub(1, std::memory_order_relaxed); } } guard;

    std::string state;
    rakuspace::CheckResult cr = rakuspace::check_user(username);
    if (cr.reached && !cr.known) return;          // bad username, skip discord
    if (include_title && cr.reached && !cr.title.empty()) state = cr.title;

    if (generation != g_stream_generation.load()) return;
    // ... unchanged from here: build Activity, url_encode(username) in button_url,
    //     generation recheck around rpc.connect(), rpc.set_activity(a)
}
```

- [ ] **Step 4: Drop dead references**

Remove `rakuspace_verify_button` (defined here for the old panel) and any remaining `RAKUSPACE_SERVICE_ID` usage. Confirm `rakuspace-service.hpp` is not included anywhere.

- [ ] **Step 5: Build**

```
cd obs-plugin && cmake --preset ubuntu-x86_64 && cmake --build --preset ubuntu-x86_64
```

Expected: clean.

- [ ] **Step 6: Rewrite `obs-plugin/README.md`**

Terse, no dashes. Cover:
- What it is. One line. Adds a Discord Rich Presence card while you stream to RakuSpace. Needs OBS 30.1 or newer.
- Install. Unzip into `%ProgramData%\obs-studio\plugins\rakuspace-obs\`. Restart OBS.
- Setup. Tools menu. "RakuSpace Stream Setup". First click opens `config.json`. Fill in your stream key and username from `/stream_info`. Set `discord_enabled` true if you want the card. Save. Click the menu item again to point OBS at the stream.
- Go live. Start Streaming as normal.
- Config keys. One line each: `stream_key`, `username`, `discord_enabled`, `discord_include_title`, `discord_status_text`.
- Deployment constants. `src/rakuspace-config.h`. `RAKUSPACE_RTMP_INGEST`, `RAKUSPACE_SITE_BASE`, `RAKUSPACE_DISCORD_APP_ID`.
- Discord app. Developer Portal. New Application. Rich Presence. Art Assets. Upload a logo with key `logo`. Copy the Application ID into the constant. No OAuth. No review.
- Build. `cmake --preset windows-x64` then `cmake --build --preset windows-x64 --config RelWithDebInfo`. Optional `-DRAKUSPACE_BUILD_SMOKE=ON` builds `rpc-smoke`.
- Scope. No connection status. No viewer count. No reconnect. No offline card.

- [ ] **Step 7: Fix the top-level README line**

Rewrite the `obs-plugin` bullet in `/home/glizzy/Projects/rakuspace/README.md`. Terse, no dashes. Something like: `obs-plugin/ is an OBS plugin that shows a Discord Rich Presence card while you stream to RakuSpace. See obs-plugin/README.md.`

- [ ] **Step 8: Commit**

```
git add -A obs-plugin README.md
git commit -m "Repoint go-live glue at the config store, rewrite plugin docs short"
```

**User VM checks:**
5. `discord_enabled` false. Start/Stop. No card.
6. `discord_enabled` true, Discord running. Start. Card shows `details` from `discord_status_text` and a Watch button at `rakuspace.apps.raku.party/live/<username>`. Stop. Card clears.
7. `discord_enabled` true, Discord not running. Start. Stream fine, no error.
8. `discord_include_title` true, real title. Line 2 shows the title. No title or timeout. One line.
9. Bad `username`. No card. Stream fine.
10. Stream to a non-RakuSpace service with `discord_enabled` true. No card.

---

## Self-review

- Old Task 4 (service registration) fully removed. No `obs_register_service`, no `obs_service_info`, no `get_connect_info` in the tree.
- Config store is the single source for Discord options. `plugin-main.cpp` never reads `obs_service_get_settings`.
- `obs_frontend_get_streaming_service` result never released. `obs_service_create` result released after set + save.
- `host_matches` compares host only, case-insensitive.
- Username validated at go-live on every path, not only when `include_title`.
- `DiscordRpc`, `check_user`, `url_encode`, generation counter, in-flight guard, `curl_global_*`, URL-encoded button username all carried over unchanged.
- No Qt anywhere. Menu item is C. File open is `ShellExecuteA` / `xdg-open`.
- No dashes in `en-US.ini`, `obs-plugin/README.md`, the top-level README line.

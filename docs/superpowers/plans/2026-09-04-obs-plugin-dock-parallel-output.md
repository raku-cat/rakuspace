# OBS plugin rework: dock plus a plugin-owned parallel output

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Replace the invisible registered service with a Qt dock that starts and stops the plugin's own RTMP output to the RakuSpace ingest, and drive Discord Rich Presence off that output's own start and stop signals.

**Architecture:** The plugin owns one `rtmp_output`, one `rtmp_custom` service, and its own video and audio encoder instances cloned from the current profile's stream encoder with B-frames forced to 0. A dock has one Go Live button, a status line, and a gear that opens a settings dialog. OBS's own streaming service is never touched. Presence is pushed on our output's `start` signal and cleared on its `stop` signal.

**Tech stack:** C++17, libobs + obs-frontend-api (OBS 30.1+), Qt6 Widgets (from the template's prebuilt dependency), libcurl, vendored `nlohmann/json`.

## Global Constraints

- No em dashes, no en dashes, no hyphen as punctuation. In every Qt string, `data/locale/en-US.ini`, `obs-plugin/README.md`, the top-level README line, commit messages, the PR body. Short. Fragments fine for labels and hints. If a line needs a comma or a dash to hold together it is too long.
- Baked constants in `obs-plugin/src/rakuspace-config.h`, unchanged: `RAKUSPACE_RTMP_INGEST` = `rtmp://live.rakuspace.on.omusubi.trans:1935/rakuspace`, `RAKUSPACE_SITE_BASE` = `https://rakuspace.apps.raku.party`, `RAKUSPACE_DISCORD_APP_ID` = `1413929830055153898`.
- No registered service. No `obs_register_service`, no `obs_service_info`, no `get_connect_info` anywhere in the tree after Task 1.
- Config store: JSON at `obs_module_config_path("config.json")`. Parent dir made with `os_mkdirs`. Paths freed with `bfree`. Vendored `nlohmann/json` at `src/vendor/nlohmann/json.hpp`. Never throws out of `load_config`.
- Parallel output service is `rtmp_custom`. Settings keys `server`, `key`, `use_auth`. `use_auth` set to `false` explicitly.
- Encoders are self-owned. `obs_video_encoder_create` / `obs_audio_encoder_create`, bound with `obs_encoder_set_video(v, obs_get_video())` and `obs_encoder_set_audio(a, obs_get_audio(), 0)`. Never shared with OBS's output.
- B-frame enforcement is our own code: on the cloned video encoder settings, `obs_data_set_int(v, "bf", 0)` and `obs_data_set_int(v, "bframes", 0)`. Nothing else on the encoder is touched. One `LOG_INFO` line. No dialog.
- Output start and stop and reconnect signals fire on libobs threads. Every dock or widget update from a signal handler goes through `QMetaObject::invokeMethod(target, ..., Qt::QueuedConnection)`. Never touch a widget directly from a signal handler.
- `obs_module_unload` stops and releases the output if it is still running, before releasing encoders and service, in that order.
- Qt comes from the template's `ENABLE_QT` option and the prebuilt `qt6` dependency in `buildspec.json`. Do not add a standalone `find_package(Qt6)` or ship a hand-built Qt.
- No automated plugin test harness. The implementer verifies with a clean `cmake --preset ubuntu-x86_64` configure and build. Windows and OBS runtime checks are run by the user on a VM and are listed per task as "User VM checks".
- Keep unchanged from the branch: `src/discord-rpc.cpp` / `.hpp`, `src/rakuspace-http.cpp` / `.hpp`, the activity payload shape, the generation counter, the in-flight guard, the `curl_global_*` calls, the URL-encoded button username. Task 5 is the only task that edits `discord-rpc.*`, and only to add a socket send and receive timeout.

**Reference:** spec `docs/superpowers/specs/2026-09-03-obs-discord-rpc-plugin-design.md`, Revision 2 at the end.

Branch: `obs-discord-rpc-plugin`. HEAD at plan start: `1f6d7bb` plus this plan's docs commit.

---

## Task 1: Delete the registered service, enable Qt, ship an empty dock and a Tools menu item

**Purpose:** Prove the Qt6 ABI path loads inside OBS on the user's Windows VM before four more tasks depend on it. Nothing in this task does real work.

**Files:**
- Delete: `obs-plugin/src/rakuspace-service.cpp`, `obs-plugin/src/rakuspace-service.hpp`
- Create: `obs-plugin/src/rakuspace-dock.hpp`, `obs-plugin/src/rakuspace-dock.cpp`
- Modify: `obs-plugin/src/plugin-main.cpp`
- Modify: `obs-plugin/CMakeLists.txt`
- Modify: `obs-plugin/CMakePresets.json`
- Modify: `obs-plugin/data/locale/en-US.ini`

**Interfaces produced (used by later tasks):**

```cpp
// rakuspace-dock.hpp
#pragma once

namespace rakuspace {
// Creates the dock widget and registers it with obs_frontend_add_dock_by_id.
// Call once from obs_module_load, after the frontend is ready.
void register_dock();
// Opens the settings dialog, parented to the OBS main window. Safe to call
// from the Qt thread only (menu callback and the dock gear button both run there).
void open_settings_dialog();
}
```

- [ ] **Step 1: Delete the service unit**

```bash
git rm obs-plugin/src/rakuspace-service.cpp obs-plugin/src/rakuspace-service.hpp
```

In `obs-plugin/src/plugin-main.cpp` remove `#include "rakuspace-service.hpp"` and the `rakuspace_register_service()` call in `obs_module_load` and any `rakuspace_verify_button` symbol and any `RAKUSPACE_SERVICE_ID` reference. Leave the rest of `plugin-main.cpp` (curl init, event callback, unload spin) in place for now. It compiles without the service.

- [ ] **Step 2: Turn on Qt in the presets**

In `obs-plugin/CMakePresets.json`, the hidden `template` preset has `"ENABLE_QT": false`. Change it to `true`:

```json
"cacheVariables": {
    "ENABLE_FRONTEND_API": true,
    "ENABLE_QT": true
}
```

`obs-plugin/CMakeLists.txt` already has, under `if(ENABLE_QT)`, the `find_package(Qt6 COMPONENTS Widgets Core)`, the `Qt6::Core Qt6::Widgets` link, and `AUTOMOC ON`. Do not add another. Confirm the dock source is included in the target so AUTOMOC processes it (Step 6).

- [ ] **Step 3: Write `rakuspace-dock.hpp`**

Exactly the interface block above.

- [ ] **Step 4: Write `rakuspace-dock.cpp` with an empty dock and a stub dialog**

```cpp
#include "rakuspace-dock.hpp"

#include <obs-module.h>
#include <obs-frontend-api.h>

#include <QWidget>
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QPushButton>
#include <QLabel>
#include <QDialog>
#include <QMainWindow>

namespace rakuspace {

static QWidget *g_dock = nullptr;

void open_settings_dialog()
{
    auto *parent = static_cast<QWidget *>(obs_frontend_get_main_window());
    QDialog dlg(parent);
    dlg.setWindowTitle("RakuSpace Settings");
    auto *lay = new QVBoxLayout(&dlg);
    lay->addWidget(new QLabel("Settings land here in Task 2.", &dlg));
    auto *ok = new QPushButton("Close", &dlg);
    QObject::connect(ok, &QPushButton::clicked, &dlg, &QDialog::accept);
    lay->addWidget(ok);
    dlg.exec();
}

void register_dock()
{
    g_dock = new QWidget();
    g_dock->setObjectName("rakuspaceDock");

    auto *root = new QVBoxLayout(g_dock);

    auto *golive = new QPushButton("Go Live to RakuSpace", g_dock);
    golive->setEnabled(false);
    root->addWidget(golive);

    auto *status = new QLabel("Offline", g_dock);
    status->setObjectName("rakuspaceStatus");
    root->addWidget(status);

    auto *row = new QHBoxLayout();
    row->addStretch();
    auto *gear = new QPushButton("Settings", g_dock);
    QObject::connect(gear, &QPushButton::clicked, [] { open_settings_dialog(); });
    row->addWidget(gear);
    root->addLayout(row);

    root->addStretch();

    obs_frontend_add_dock_by_id("rakuspace_dock", "RakuSpace", g_dock);
}

} // namespace rakuspace
```

Note: `obs_frontend_add_dock_by_id` takes ownership of the widget. Do not delete `g_dock` in unload.

- [ ] **Step 5: Wire into `plugin-main.cpp`**

Add `#include "rakuspace-dock.hpp"`. In `obs_module_load`, after `curl_global_init` and after `obs_frontend_add_event_callback` is set up, add:

```cpp
    rakuspace::register_dock();
    obs_frontend_add_tools_menu_item("RakuSpace Settings",
        [](void *) { rakuspace::open_settings_dialog(); }, nullptr);
```

`obs_frontend_add_tools_menu_item`'s callback signature is `void (*)(void *)`. A captureless lambda converts. Keep it captureless.

- [ ] **Step 6: CMake sources and locale**

In `obs-plugin/CMakeLists.txt` add to the target sources, next to the other `src/*.cpp`:

```
    src/rakuspace-dock.cpp
```

Remove `src/rakuspace-service.cpp` from the sources list.

Reduce `obs-plugin/data/locale/en-US.ini` to one line (the file has to exist for `OBS_MODULE_USE_DEFAULT_LOCALE`):

```
# no localized strings
```

- [ ] **Step 7: Configure and build on Linux**

```bash
cd obs-plugin && cmake --preset ubuntu-x86_64 && cmake --build --preset ubuntu-x86_64
```

Expected: Qt6 is found (from the template dependency), AUTOMOC runs on `rakuspace-dock.cpp`, clean compile and link, no undefined symbols, no warnings.

- [ ] **Step 8: Commit**

```bash
git add -A obs-plugin
git commit -m "Swap the registered service for a Qt dock shell and a settings menu item"
```

**User VM checks:**
1. Build with `cmake --preset windows-x64` then `cmake --build --preset windows-x64 --config RelWithDebInfo`.
2. Install the built `rakuspace-obs` into OBS. OBS starts, the plugin loads with no Qt DLL error.
3. A "RakuSpace" dock is present (View menu, Docks). It has a disabled "Go Live to RakuSpace" button, an "Offline" label, and a "Settings" button.
4. Tools menu has "RakuSpace Settings". Clicking it, or the dock's Settings button, opens a small dialog with a Close button.

---

## Task 2: Config store and the settings dialog

**Purpose:** Persist stream key, username, and the Discord options, and give the dialog real fields.

**Files:**
- Create: `obs-plugin/src/rakuspace-config-store.hpp`, `obs-plugin/src/rakuspace-config-store.cpp`
- Modify: `obs-plugin/src/rakuspace-dock.cpp` (real dialog)
- Modify: `obs-plugin/CMakeLists.txt` (add the source)

**Interfaces produced:**

```cpp
// rakuspace-config-store.hpp
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
```

**Interfaces consumed:** none new.

- [ ] **Step 1: Write `rakuspace-config-store.hpp`**

Exactly the block above.

- [ ] **Step 2: Write `rakuspace-config-store.cpp`**

```cpp
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
}

} // namespace rakuspace
```

- [ ] **Step 3: Add the source to CMake**

`obs-plugin/CMakeLists.txt` target sources, add:

```
    src/rakuspace-config-store.cpp
```

- [ ] **Step 4: Replace the stub dialog in `rakuspace-dock.cpp`**

Add includes:

```cpp
#include "rakuspace-config-store.hpp"

#include <QLineEdit>
#include <QCheckBox>
#include <QFormLayout>
#include <QDialogButtonBox>
```

Replace `open_settings_dialog` with:

```cpp
void open_settings_dialog()
{
    auto *parent = static_cast<QWidget *>(obs_frontend_get_main_window());
    QDialog dlg(parent);
    dlg.setWindowTitle("RakuSpace Settings");

    Config c = load_config();

    auto *key = new QLineEdit(QString::fromStdString(c.stream_key), &dlg);
    key->setEchoMode(QLineEdit::Password);
    auto *user = new QLineEdit(QString::fromStdString(c.username), &dlg);
    auto *disc = new QCheckBox("Share status to Discord", &dlg);
    disc->setChecked(c.discord_enabled);
    auto *title = new QCheckBox("Include stream title", &dlg);
    title->setChecked(c.discord_include_title);
    auto *statusText =
        new QLineEdit(QString::fromStdString(c.discord_status_text), &dlg);

    auto sync = [&] {
        title->setEnabled(disc->isChecked());
        statusText->setEnabled(disc->isChecked());
    };
    QObject::connect(disc, &QCheckBox::toggled, &dlg, sync);
    sync();

    auto *form = new QFormLayout();
    form->addRow("Stream key", key);
    form->addRow("Username", user);
    form->addRow(disc);
    form->addRow(title);
    form->addRow("Status text", statusText);

    auto *bb = new QDialogButtonBox(
        QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dlg);
    QObject::connect(bb, &QDialogButtonBox::accepted, &dlg, &QDialog::accept);
    QObject::connect(bb, &QDialogButtonBox::rejected, &dlg, &QDialog::reject);

    auto *root = new QVBoxLayout(&dlg);
    root->addLayout(form);
    root->addWidget(bb);

    if (dlg.exec() != QDialog::Accepted)
        return;

    c.stream_key = key->text().toStdString();
    c.username = user->text().toStdString();
    c.discord_enabled = disc->isChecked();
    c.discord_include_title = title->isChecked();
    c.discord_status_text = statusText->text().toStdString();
    if (!save_config(c))
        blog(LOG_WARNING, "[rakuspace-obs] could not write config.json");
}
```

- [ ] **Step 5: Build**

```bash
cd obs-plugin && cmake --preset ubuntu-x86_64 && cmake --build --preset ubuntu-x86_64
```

Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add -A obs-plugin
git commit -m "Add the config store and the real settings dialog"
```

**User VM checks:**
1. Open settings, enter a key and username, tick Share status to Discord, set status text, OK.
2. Reopen. All values are still there. The key field shows dots.
3. Untick Share status to Discord. The title checkbox and status text go disabled.
4. `%AppData%\obs-studio\plugin_config\rakuspace-obs\config.json` exists and is readable JSON.

---

## Task 3: The output manager, self-owned encoders, B-frames off

**Purpose:** Start and stop a real RTMP output to the RakuSpace ingest, with our own encoders and no B-frames, and expose start and stop and reconnect through a callback the dock will use in Task 4.

**Files:**
- Create: `obs-plugin/src/rakuspace-output.hpp`, `obs-plugin/src/rakuspace-output.cpp`
- Modify: `obs-plugin/CMakeLists.txt` (add the source)

**Interfaces produced:**

```cpp
// rakuspace-output.hpp
#pragma once
#include <functional>
#include <string>

namespace rakuspace {

enum class OutputEvent { Started, Stopped, Reconnecting, ReconnectSuccess };

// cb is invoked from libobs signal threads, not the Qt thread. The receiver
// marshals to the UI thread. `code` is meaningful only for Stopped: 0 is a
// clean stop, non zero is an error stop (already gave up on reconnect).
using OutputCallback = std::function<void(OutputEvent ev, int code)>;

class OutputManager {
public:
    static OutputManager &instance();

    void set_callback(OutputCallback cb);   // Qt thread, before start

    // Builds service, encoders, output and starts. Returns false if it could
    // not even begin (empty key, encoder create failure). A true return does
    // not mean connected, the Started event does.
    bool start(const std::string &stream_key);

    void stop();                            // async, the Stopped event follows
    bool active() const;

    void shutdown();                        // obs_module_unload, blocking

private:
    OutputManager() = default;
    struct Impl;
    Impl *d = nullptr;
};

}
```

**Interfaces consumed:** `rakuspace-config.h` for `RAKUSPACE_RTMP_INGEST`.

- [ ] **Step 1: Write `rakuspace-output.hpp`**

Exactly the block above.

- [ ] **Step 2: Write the encoder cloning helper in `rakuspace-output.cpp`**

Start the file:

```cpp
#include "rakuspace-output.hpp"
#include "rakuspace-config.h"

#include <obs.h>
#include <obs-module.h>
#include <obs-frontend-api.h>
#include <util/config-file.h>
#include <util/platform.h>

#include <atomic>
#include <mutex>
#include <string>

namespace rakuspace {

// Resolve the encoder id the user has picked for streaming in the current
// profile. Simple mode maps a short name to a concrete id. Advanced mode
// stores the id directly. Falls back to "obs_x264".
static std::string resolve_stream_encoder_id()
{
    config_t *p = obs_frontend_get_profile_config();
    if (!p)
        return "obs_x264";

    const char *mode = config_get_string(p, "Output", "Mode");
    bool advanced = mode && (strcmp(mode, "Advanced") == 0 ||
                             strcmp(mode, "advanced") == 0);

    if (advanced) {
        const char *id = config_get_string(p, "AdvOut", "Encoder");
        if (id && *id)
            return id;
        return "obs_x264";
    }

    const char *simple = config_get_string(p, "SimpleOutput", "StreamEncoder");
    if (!simple)
        return "obs_x264";
    // OBS simple mode short names. Match get_simple_output_encoder() in OBS.
    if (strcmp(simple, "x264") == 0 || strcmp(simple, "x264_lowcpu") == 0)
        return "obs_x264";
    if (strcmp(simple, "nvenc") == 0)
        return "jim_nvenc";
    if (strcmp(simple, "nvenc_hevc") == 0)
        return "jim_hevc_nvenc";
    if (strcmp(simple, "nvenc_av1") == 0)
        return "jim_av1_nvenc";
    if (strcmp(simple, "qsv") == 0)
        return "obs_qsv11_v2";
    if (strcmp(simple, "qsv_av1") == 0)
        return "obs_qsv11_av1";
    if (strcmp(simple, "amd") == 0)
        return "h264_texture_amf";
    if (strcmp(simple, "amd_hevc") == 0)
        return "h265_texture_amf";
    if (strcmp(simple, "amd_av1") == 0)
        return "av1_texture_amf";
    if (strcmp(simple, "apple_h264") == 0)
        return "com.apple.videotoolbox.videoencoder.ave.avc";
    return "obs_x264";
}

// Build the video encoder settings. Simple mode: pull VBitrate and rate
// control from the profile. Advanced mode: load the profile's
// streamEncoder.json. Then force bf and bframes to 0.
static obs_data_t *build_video_settings()
{
    config_t *p = obs_frontend_get_profile_config();
    obs_data_t *v = nullptr;

    const char *mode = p ? config_get_string(p, "Output", "Mode") : nullptr;
    bool advanced = mode && (strcmp(mode, "Advanced") == 0 ||
                             strcmp(mode, "advanced") == 0);

    if (advanced) {
        char *dir = obs_frontend_get_current_profile_path();
        if (dir) {
            std::string path = std::string(dir) + "/streamEncoder.json";
            bfree(dir);
            v = obs_data_create_from_json_file(path.c_str());
        }
    }
    if (!v)
        v = obs_data_create();

    if (!advanced && p) {
        long long vb = config_get_int(p, "SimpleOutput", "VBitrate");
        if (vb <= 0)
            vb = 6000;
        obs_data_set_int(v, "bitrate", vb);
        if (!obs_data_has_user_value(v, "rate_control"))
            obs_data_set_string(v, "rate_control", "CBR");
    }
    if (!obs_data_has_user_value(v, "bitrate"))
        obs_data_set_int(v, "bitrate", 6000);

    // Our one enforcement. Nothing else on the encoder is touched.
    obs_data_set_int(v, "bf", 0);
    obs_data_set_int(v, "bframes", 0);
    blog(LOG_INFO, "[rakuspace-obs] B-frames set to 0 for OME low latency");

    return v;
}

static obs_data_t *build_audio_settings()
{
    config_t *p = obs_frontend_get_profile_config();
    obs_data_t *a = obs_data_create();
    long long ab = p ? config_get_int(p, "SimpleOutput", "ABitrate") : 160;
    if (ab <= 0)
        ab = 160;
    obs_data_set_int(a, "bitrate", ab);
    return a;
}
```

Note for the implementer: confirm `obs_frontend_get_current_profile_path` and the `Output/Mode`, `SimpleOutput/VBitrate`, `SimpleOutput/ABitrate`, `AdvOut/Encoder` keys against `/usr/include/obs/obs-frontend-api.h` and the OBS source. If `obs_frontend_get_current_profile_path` is absent in the installed headers, drop advanced-mode `streamEncoder.json` loading and always start from `obs_data_create()` plus the simple-mode bitrate, and note the change in the report. The B-frame lines and the simple-mode path must stay.

- [ ] **Step 3: Write the `Impl` and lifecycle in `rakuspace-output.cpp`**

```cpp
struct OutputManager::Impl {
    std::mutex mtx;
    obs_output_t *output = nullptr;
    obs_service_t *service = nullptr;
    obs_encoder_t *venc = nullptr;
    obs_encoder_t *aenc = nullptr;
    OutputCallback cb;
    std::atomic<bool> running{false};
};

OutputManager &OutputManager::instance()
{
    static OutputManager m;
    if (!m.d)
        m.d = new Impl();
    return m;
}

void OutputManager::set_callback(OutputCallback cb)
{
    d->cb = std::move(cb);
}

bool OutputManager::active() const
{
    return d->running.load();
}

static void fire(OutputManager::Impl *d, OutputEvent ev, int code)
{
    if (d->cb)
        d->cb(ev, code);
}

static void on_start(void *param, calldata_t *)
{
    auto *d = static_cast<OutputManager::Impl *>(param);
    d->running.store(true);
    fire(d, OutputEvent::Started, 0);
}

static void on_stop(void *param, calldata_t *cd)
{
    auto *d = static_cast<OutputManager::Impl *>(param);
    long long code = 0;
    calldata_get_int(cd, "code", &code);
    d->running.store(false);
    fire(d, OutputEvent::Stopped, (int)code);
}

static void on_reconnect(void *param, calldata_t *)
{
    fire(static_cast<OutputManager::Impl *>(param),
         OutputEvent::Reconnecting, 0);
}

static void on_reconnect_success(void *param, calldata_t *)
{
    fire(static_cast<OutputManager::Impl *>(param),
         OutputEvent::ReconnectSuccess, 0);
}

bool OutputManager::start(const std::string &stream_key)
{
    std::lock_guard<std::mutex> lk(d->mtx);
    if (d->output)
        return false;
    if (stream_key.empty()) {
        blog(LOG_WARNING, "[rakuspace-obs] stream key is empty");
        return false;
    }

    obs_data_t *svc_s = obs_data_create();
    obs_data_set_string(svc_s, "server", RAKUSPACE_RTMP_INGEST);
    obs_data_set_string(svc_s, "key", stream_key.c_str());
    obs_data_set_bool(svc_s, "use_auth", false);
    d->service = obs_service_create("rtmp_custom", "rakuspace_out_service",
                                    svc_s, nullptr);
    obs_data_release(svc_s);
    if (!d->service) {
        blog(LOG_WARNING, "[rakuspace-obs] service create failed");
        return false;
    }

    std::string enc_id = resolve_stream_encoder_id();

    obs_data_t *v_s = build_video_settings();
    d->venc = obs_video_encoder_create(enc_id.c_str(), "rakuspace_venc",
                                       v_s, nullptr);
    obs_data_release(v_s);
    if (!d->venc) {
        blog(LOG_WARNING, "[rakuspace-obs] video encoder %s failed, using obs_x264",
             enc_id.c_str());
        obs_data_t *fx = obs_data_create();
        obs_data_set_int(fx, "bitrate", 6000);
        obs_data_set_string(fx, "rate_control", "CBR");
        obs_data_set_int(fx, "bf", 0);
        obs_data_set_int(fx, "bframes", 0);
        d->venc = obs_video_encoder_create("obs_x264", "rakuspace_venc",
                                           fx, nullptr);
        obs_data_release(fx);
    }

    obs_data_t *a_s = build_audio_settings();
    d->aenc = obs_audio_encoder_create("ffmpeg_aac", "rakuspace_aenc",
                                       a_s, 0, nullptr);
    obs_data_release(a_s);

    if (!d->venc || !d->aenc) {
        blog(LOG_WARNING, "[rakuspace-obs] encoder create failed, aborting start");
        stop_locked();  // see Step 4
        return false;
    }

    obs_encoder_set_video(d->venc, obs_get_video());
    obs_encoder_set_audio(d->aenc, obs_get_audio());

    d->output = obs_output_create("rtmp_output", "rakuspace_out",
                                  nullptr, nullptr);
    if (!d->output) {
        blog(LOG_WARNING, "[rakuspace-obs] output create failed");
        stop_locked();
        return false;
    }
    obs_output_set_service(d->output, d->service);
    obs_output_set_video_encoder(d->output, d->venc);
    obs_output_set_audio_encoder(d->output, d->aenc, 0);
    obs_output_set_reconnect_settings(d->output, 20, 10);  // retries, sec

    signal_handler_t *sh = obs_output_get_signal_handler(d->output);
    signal_handler_connect(sh, "start", on_start, d);
    signal_handler_connect(sh, "stop", on_stop, d);
    signal_handler_connect(sh, "reconnect", on_reconnect, d);
    signal_handler_connect(sh, "reconnect_success", on_reconnect_success, d);

    if (!obs_output_start(d->output)) {
        const char *err = obs_output_get_last_error(d->output);
        blog(LOG_WARNING, "[rakuspace-obs] output start failed: %s",
             err ? err : "unknown");
        stop_locked();
        return false;
    }
    return true;
}
```

Confirm `obs_output_set_reconnect_settings` exists in the installed headers. If it is absent, drop that line, `rtmp_output` reconnects with its own defaults, and note it.

- [ ] **Step 4: Write `stop`, `stop_locked`, `shutdown` in `rakuspace-output.cpp`**

```cpp
// caller holds d->mtx
static void stop_locked_impl(OutputManager::Impl *d)
{
    if (d->output) {
        signal_handler_t *sh = obs_output_get_signal_handler(d->output);
        signal_handler_disconnect(sh, "start", on_start, d);
        signal_handler_disconnect(sh, "stop", on_stop, d);
        signal_handler_disconnect(sh, "reconnect", on_reconnect, d);
        signal_handler_disconnect(sh, "reconnect_success",
                                  on_reconnect_success, d);
        obs_output_stop(d->output);
        obs_output_release(d->output);
        d->output = nullptr;
    }
    if (d->venc) {
        obs_encoder_release(d->venc);
        d->venc = nullptr;
    }
    if (d->aenc) {
        obs_encoder_release(d->aenc);
        d->aenc = nullptr;
    }
    if (d->service) {
        obs_service_release(d->service);
        d->service = nullptr;
    }
    d->running.store(false);
}
```

Make `stop_locked()` in Step 3 call `stop_locked_impl(d)`. Public `stop`:

```cpp
void OutputManager::stop()
{
    std::lock_guard<std::mutex> lk(d->mtx);
    if (d->output && obs_output_active(d->output)) {
        obs_output_stop(d->output);   // graceful, on_stop will clean up state
        return;
    }
    stop_locked_impl(d);
}
```

Design note for the implementer: on a graceful `stop`, `on_stop` fires from a libobs thread while we may still be inside a locked section elsewhere. Keep `on_stop` doing only `running.store(false)` plus `fire`. Do the object release from `shutdown` and from the next `start`'s guard, or add a small deferred release. Do not call `obs_output_release` from inside the `stop` signal handler. Pick the simplest correct arrangement and describe it in the report.

```cpp
void OutputManager::shutdown()
{
    std::lock_guard<std::mutex> lk(d->mtx);
    if (d->output && obs_output_active(d->output)) {
        obs_output_stop(d->output);
        for (int i = 0; i < 200 && obs_output_active(d->output); ++i)
            os_sleep_ms(10);
        obs_output_force_stop(d->output);
    }
    stop_locked_impl(d);
}
```

- [ ] **Step 5: Add the source to CMake**

`obs-plugin/CMakeLists.txt` target sources:

```
    src/rakuspace-output.cpp
```

- [ ] **Step 6: Call `shutdown` from unload**

In `obs-plugin/src/plugin-main.cpp` `obs_module_unload`, before `curl_global_cleanup`, add:

```cpp
    rakuspace::OutputManager::instance().shutdown();
```

with `#include "rakuspace-output.hpp"`.

- [ ] **Step 7: Build**

```bash
cd obs-plugin && cmake --preset ubuntu-x86_64 && cmake --build --preset ubuntu-x86_64
```

Expected: clean. No missing symbols. Warnings from the header-key confirmations resolved.

- [ ] **Step 8: Commit**

```bash
git add -A obs-plugin
git commit -m "Add the parallel output manager with self owned encoders and B-frames off"
```

**User VM checks:** none for this task alone, the dock is not wired yet. Covered in Task 4.

---

## Task 4: Wire the dock to the output manager

**Purpose:** The button starts and stops the output. The status line and button label track the output's real state, updated safely from libobs threads.

**Files:**
- Modify: `obs-plugin/src/rakuspace-dock.cpp`

**Interfaces consumed:** `OutputManager` from Task 3, `Config` and `load_config` from Task 2.

- [ ] **Step 1: Give the dock a controller object with slots**

At the top of `rakuspace-dock.cpp` add includes and a small QObject:

```cpp
#include "rakuspace-output.hpp"

#include <QObject>
#include <QTimer>
#include <QMetaObject>
#include <QElapsedTimer>

namespace rakuspace {

class DockController : public QObject {
    Q_OBJECT
public:
    QPushButton *button = nullptr;
    QLabel *status = nullptr;
    QTimer tick;
    QElapsedTimer since;
    bool live = false;

    DockController()
    {
        tick.setInterval(1000);
        connect(&tick, &QTimer::timeout, this, &DockController::refreshElapsed);
    }

public slots:
    void onToggle()
    {
        if (OutputManager::instance().active() || live) {
            OutputManager::instance().stop();
            return;
        }
        Config c = load_config();
        if (c.stream_key.empty()) {
            status->setText("Set your stream key in Settings");
            return;
        }
        button->setEnabled(false);
        status->setText("Connecting");
        if (!OutputManager::instance().start(c.stream_key)) {
            status->setText("Could not start, check the log");
            button->setEnabled(true);
        }
    }

    void onStarted()
    {
        live = true;
        since.start();
        tick.start();
        button->setText("Stop");
        button->setEnabled(true);
        refreshElapsed();
    }

    void onReconnecting() { status->setText("Reconnecting"); }

    void onReconnectSuccess() { refreshElapsed(); }

    void onStopped(int code)
    {
        live = false;
        tick.stop();
        button->setText("Go Live to RakuSpace");
        button->setEnabled(true);
        status->setText(code == 0 ? "Offline" : "Offline, stream ended early");
    }

    void refreshElapsed()
    {
        if (!live) return;
        qint64 s = since.elapsed() / 1000;
        status->setText(QString("Live %1:%2:%3")
            .arg(s / 3600, 2, 10, QChar('0'))
            .arg((s % 3600) / 60, 2, 10, QChar('0'))
            .arg(s % 60, 2, 10, QChar('0')));
    }
};

}
```

Because this file now has a `Q_OBJECT`, AUTOMOC needs the moc include. Add at the very bottom of the file:

```cpp
#include "rakuspace-dock.moc"
```

- [ ] **Step 2: Build the controller in `register_dock` and connect the callback**

In `register_dock`, after the widgets exist:

```cpp
    static DockController ctl;
    ctl.button = golive;
    ctl.status = status;
    golive->setEnabled(true);
    QObject::connect(golive, &QPushButton::clicked, &ctl,
                     &DockController::onToggle);

    OutputManager::instance().set_callback(
        [](OutputEvent ev, int code) {
            // libobs thread. Marshal to the Qt thread.
            QMetaObject::invokeMethod(qApp, [ev, code] {
                extern rakuspace::DockController *g_ctl;
                if (!g_ctl) return;
                switch (ev) {
                case OutputEvent::Started:          g_ctl->onStarted(); break;
                case OutputEvent::Reconnecting:     g_ctl->onReconnecting(); break;
                case OutputEvent::ReconnectSuccess: g_ctl->onReconnectSuccess(); break;
                case OutputEvent::Stopped:          g_ctl->onStopped(code); break;
                }
            }, Qt::QueuedConnection);
        });
```

Cleaner: make the controller a file-scope pointer instead of `extern` gymnastics. Use:

```cpp
static DockController *g_ctl = nullptr;
```

at file scope, set `g_ctl = &ctl;` in `register_dock`, and have the lambda capture nothing and read `g_ctl`. Keep `qApp` as the invoke target so the call lands on the Qt main thread. The implementer picks the tidiest form, the requirement is: the callback never touches a widget except through `QMetaObject::invokeMethod(..., Qt::QueuedConnection)`.

- [ ] **Step 3: Build**

```bash
cd obs-plugin && cmake --preset ubuntu-x86_64 && cmake --build --preset ubuntu-x86_64
```

Expected: `rakuspace-dock.moc` is generated, clean compile and link.

- [ ] **Step 4: Commit**

```bash
git add -A obs-plugin
git commit -m "Wire the dock button and status line to the output manager"
```

**User VM checks:**
1. Set a valid key in Settings. Dock button is enabled.
2. Click it. Status goes Connecting, then Live with a running timer. Button reads Stop. Playback works at `/live/<username>`.
3. Click Stop. Status Offline, button resets.
4. OBS Settings > Stream is untouched. OBS's own Start Streaming still works on its own.
5. Pull the network while live. Status shows Reconnecting. Restore. Back to Live.
6. Close OBS while live. It exits without hanging.

---

## Task 5: Discord presence off the output signals, socket timeout, strings and docs

**Purpose:** Push the Rich Presence card when our output starts, clear it when it stops. Make the Discord pipe non blocking so a wedged Discord never blocks a libobs thread. Rewrite the docs and the PR body short.

**Files:**
- Modify: `obs-plugin/src/plugin-main.cpp`
- Modify: `obs-plugin/src/discord-rpc.cpp` (socket timeout only)
- Modify: `obs-plugin/src/rakuspace-output.cpp` or `rakuspace-dock.cpp` (hook the presence calls, implementer's choice, see below)
- Modify: `obs-plugin/README.md`
- Modify: `README.md` (top level obs-plugin line)
- PR #6 body on the forge (controller does this, not a code change)

**Interfaces consumed:** `OutputManager` callback from Task 3, `Config` from Task 2, `rakuspace::DiscordRpc`, `rakuspace::Activity`, `rakuspace::check_user`, `rakuspace::url_encode`, the existing `build_and_push_activity`, `g_stream_generation`, `g_inflight` from the current `plugin-main.cpp`.

- [ ] **Step 1: Remove the old frontend event path for presence**

In `plugin-main.cpp`, delete the `OBS_FRONTEND_EVENT_STREAMING_STARTED` and `OBS_FRONTEND_EVENT_STREAMING_STOPPED` handling that pushed and cleared presence. Keep `g_stream_generation`, `g_inflight`, `build_and_push_activity`, the `InflightGuard`, `curl_global_init` and `curl_global_cleanup`, and the bounded `g_inflight` spin in unload. If nothing else uses the frontend event callback after this, remove `obs_frontend_add_event_callback` and its `obs_frontend_remove_event_callback` too.

- [ ] **Step 2: Expose a presence entry point**

Add to `plugin-main.cpp`, in the `rakuspace` namespace, declared in a small new header `obs-plugin/src/rakuspace-presence.hpp` so the output layer can call it:

```cpp
// rakuspace-presence.hpp
#pragma once
namespace rakuspace {
void presence_on_live();    // reads config, spawns the detached activity push
void presence_on_offline(); // clears the card, detached, bounded
}
```

`presence_on_live` body: read `load_config()`, return if `!discord_enabled || username.empty()`, then the same generation bump, `g_inflight` add, and detached `std::thread(build_and_push_activity, gen, c.username, c.discord_include_title, c.discord_status_text, (int64_t)time(nullptr)).detach();` that the old `STREAMING_STARTED` path used.

`presence_on_offline` body: bump `g_stream_generation` so any in-flight push is stale, then a detached worker that calls `DiscordRpc::instance().clear()` and `close()`, guarded by the same `InflightGuard` so unload waits for it.

- [ ] **Step 3: Call presence from the output callback**

In the dock's `OutputManager` callback (Task 4 Step 2), add:

```cpp
case OutputEvent::Started:  g_ctl->onStarted();  rakuspace::presence_on_live();    break;
...
case OutputEvent::Stopped:  g_ctl->onStopped(code); rakuspace::presence_on_offline(); break;
```

`presence_on_live` and `presence_on_offline` are safe to call from the Qt thread, they only spawn detached workers. Do not call `DiscordRpc` directly on the Qt thread or a libobs thread.

- [ ] **Step 4: Socket timeout in `discord-rpc.cpp`**

Where the pipe or unix socket is opened, set a send and receive timeout so a stuck Discord cannot block a caller. POSIX:

```cpp
struct timeval tv{0, 300000};  // 300 ms
setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));
setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
```

Windows named pipe: after `CreateFile`, the pipe is byte mode. Guard every `WriteFile` and `ReadFile` result and on failure `impl_->pipe.reset()` and set `ready` false, which the code already does for closed-pipe detection. Add a comment that the 2-writes-per-session usage plus closed-pipe reset is the timeout strategy on Windows, no overlapped I/O. Keep the change minimal, do not restructure the client.

- [ ] **Step 5: Build**

```bash
cd obs-plugin && cmake --preset ubuntu-x86_64 && cmake --build --preset ubuntu-x86_64
```

Expected: clean.

- [ ] **Step 6: Rewrite `obs-plugin/README.md`**

Terse, no dashes. Cover:
- What it is. One line. Shows a Discord Rich Presence card while you stream to RakuSpace. Needs OBS 30.1 or newer.
- Install. Unzip into the OBS plugins folder. Restart OBS.
- Setup. Open the RakuSpace dock. Click Settings. Enter your stream key and username from `/stream_info`. Tick Share status to Discord if you want the card. OK.
- Go live. Click Go Live to RakuSpace in the dock. Click Stop to end it. OBS's own Start Streaming is separate and still works.
- Config keys, one line each: `stream_key`, `username`, `discord_enabled`, `discord_include_title`, `discord_status_text`. File at the plugin config path, `config.json`.
- Encoder. Uses your OBS stream encoder settings. Forces B-frames to 0 for OME low latency. Nothing else changed.
- Deployment constants. `src/rakuspace-config.h`. `RAKUSPACE_RTMP_INGEST`, `RAKUSPACE_SITE_BASE`, `RAKUSPACE_DISCORD_APP_ID`.
- Discord app. Developer Portal. New Application. Rich Presence. Art Assets. Upload a logo with key `logo`. Copy the Application ID into the constant. No OAuth. No review.
- Build. `cmake --preset windows-x64` then `cmake --build --preset windows-x64 --config RelWithDebInfo`. Optional `-DRAKUSPACE_BUILD_SMOKE=ON` builds `rpc-smoke`.
- Scope. No viewer count. No connection status readout beyond the dock. No offline card.

- [ ] **Step 7: Fix the top level README line**

In `/home/glizzy/Projects/rakuspace/README.md` rewrite the `obs-plugin` bullet. Terse, no dashes. `obs-plugin/ is an OBS plugin. It adds a dock to stream to RakuSpace and shows a Discord Rich Presence card while you are live. See obs-plugin/README.md.`

- [ ] **Step 8: Commit**

```bash
git add -A obs-plugin README.md
git commit -m "Drive Discord presence off the output signals, add a pipe timeout, rewrite docs short"
```

**User VM checks:**
1. `discord_enabled` false. Go live via the dock. No card.
2. `discord_enabled` true, Discord running. Go live. Card shows the status text and a Watch button at `rakuspace.apps.raku.party/live/<username>`. Stop. Card clears.
3. `discord_enabled` true, Discord not running. Go live. Stream fine, no error, no hang.
4. `discord_include_title` true, real title. Line 2 shows the title. No title or a timeout: one line.
5. Bad username. No card. Stream still goes live.
6. Close OBS while live with Discord running. It exits without hanging.

---

## Self-review

- `rakuspace-service.cpp` / `.hpp` deleted. No `obs_register_service`, no `obs_service_info`, no `get_connect_info` in the tree.
- `ENABLE_QT` on in the presets. No standalone `find_package(Qt6)` added. Dock source in the target so AUTOMOC runs. `.moc` include present where `Q_OBJECT` is used.
- Config store is the single source for stream key, username, Discord options. Nothing reads `obs_service_get_settings`.
- Parallel output uses `rtmp_custom` with `server`, `key`, `use_auth` false. Self-owned encoders bound to `obs_get_video()` / `obs_get_audio()`. Never shared.
- B-frame enforcement is `bf` and `bframes` set to 0 on the cloned video settings, plus one log line. No codec, rate control, bitrate, preset, or profile touched. No modal.
- Output start, stop, reconnect, reconnect_success handled. Every widget update from a handler goes through `QMetaObject::invokeMethod(..., Qt::QueuedConnection)`. `stop` reads `calldata_get_int(cd, "code")` for the status text and the log only.
- `obs_module_unload` stops and force stops the output if running, then releases output, encoders, service in that order, then the existing `g_inflight` spin and `curl_global_cleanup`.
- Presence pushed on our output `Started`, cleared on `Stopped`. No `OBS_FRONTEND_EVENT_STREAMING_*` for presence. Generation counter, in-flight guard, bounded unload spin carried over.
- Discord socket has a short send and receive timeout on POSIX, closed-pipe reset on Windows. `DiscordRpc` never called on the Qt or a libobs thread, only from detached workers.
- No em dashes, no en dashes, no hyphen as punctuation in `en-US.ini`, `obs-plugin/README.md`, the top level README line, commit messages, the PR body.
- Manual test matrix in the spec Revision 2 updated, old dropdown items gone.

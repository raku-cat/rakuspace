# OBS plugin: RakuSpace streaming service + Discord Rich Presence

**Date:** 2026-09-03
**Status:** Approved (design)

## Goal

Ship an OBS Studio plugin that gives RakuSpace streamers two things:

1. A first-class **"RakuSpace" streaming service** in Settings → Stream, so setup is
   "pick RakuSpace, paste your key, type your username" instead of hand-configuring a
   custom RTMP server.
2. An optional **Discord Rich Presence card** that appears on the streamer's Discord
   profile while they are live, with a "Watch Stream" button pointing at their
   `rakuspace.site/live/<username>` page.

Scope is deliberately narrow ("light touch"): no connection-status UI, no viewer
count, no reconnect logic, no offline/"was live" presence.

## Background / constraints

- **Discord Rich Presence needs no Discord review.** The approval gate the project
  hit earlier is specific to *Activities* (the Embedded App SDK). Classic Rich
  Presence just needs an Application ID from the Developer Portal.
- **The plugin cannot derive the username from the stream key or from OME.** OME's
  `new_url` rewrite in `verify_webhook()` (`frontend/RakuSpace.py:1175`) happens
  entirely inside OME; OBS publishes RTMP and never receives the rewritten URL back
  (RTMP has no publisher-redirect). The stream-key prefix is a numeric `userid`
  (autoincrement int), not the username. So the username must be its own typed
  field, used only for the `/live/<username>` link and the validate/title fetch —
  never for publish auth.
- **Target platform is Windows x64.** The plugin stays cross-platform-buildable for
  local compile-checks on Linux, but Windows is the only tested and shipped target.
- **OBS 30.1 is the minimum version** (signed off). Lets us implement only the
  modern `get_connect_info` service path and skip pre-30.1 `get_url`/`get_key`.

## Repo layout

New top-level directory `obs-plugin/` in the rakuspace repo, sibling to `frontend/`
and `backend/`. (Not `vendor/` — that conventionally means vendored third-party
code; this is first-party. `integrations/obs-plugin/` is an acceptable alternative
if a namespace for future client-side pieces is wanted; flat matches the repo's
current style.)

Built from the official `obsproject/obs-plugin-template` (CMake presets).

Module name: `rakuspace-obs`, module id `rakuspace`. Single C++ module, three
internal units.

## Component 1 — `service.cpp`: the "RakuSpace" streaming service

Registered via `obs_register_service()` with an `obs_service_info` struct. Does not
set `OBS_SERVICE_INTERNAL`, so it appears in the Settings → Stream service list.

- `get_name` → `"RakuSpace"`
- `get_properties` → the panel described below
- `get_connect_info` → returns, keyed by the `OBS_SERVICE_CONNECT_INFO_*` enum:
  - `SERVER_URL` = the compile-time constant `RAKUSPACE_RTMP_INGEST`
    (e.g. `rtmp://park.raku.party:1935/live` — confirm exact host/port/app against
    the live deployment during implementation)
  - `STREAM_KEY` = the "Stream Key" field value, verbatim (`<userid>_<streamkey>`)
- No server field in the panel. A streamer on a nonstandard ingest switches OBS's
  service dropdown back to "Custom" and configures it the pre-existing way.

**Risk to verify early:** confirm a third-party `obs_register_service` entry shows
up in the Settings → Stream dropdown on OBS 30.1+ (it may land under a "More…"
grouping). If it does not surface acceptably, fall back to documenting the Custom
service + a separate Tools-menu config for the Discord half.

### Service properties panel (Settings → Stream, service = "RakuSpace")

| Field | Key | Type | Default | Purpose |
|---|---|---|---|---|
| Username | `username` | text | — | RakuSpace login name. Display/link only; never used for publish auth. |
| Stream Key | `stream_key` | text (OBS renders masked) | — | `<userid>_<streamkey>` copied verbatim from `/stream_info`. Authenticates the publish. |
| Verify username | `verify_btn` | button | — | Async `GET {RAKUSPACE_SITE_BASE}/api/check/<username>`; sets an inline result ("✓ found" / "✗ not found"). Advisory only, blocks nothing. |
| Share status to Discord | `discord_enabled` | bool | off | Master toggle for the Discord half. |
| Include stream title in the card | `discord_include_title` | bool | off | Enabled only when `discord_enabled` is on. |
| Status text | `discord_status_text` | text | `Live on RakuSpace` | Enabled only when `discord_enabled` is on. Becomes the card's `details` line. |

Enable/disable of the two sub-fields is driven by a `modified_callback` on
`discord_enabled` calling `obs_property_set_enabled()`.

Settings persist in the OBS service config (per profile) — no separate config file.
The plugin reads them at go-live via
`obs_frontend_get_streaming_service()` → `obs_service_get_settings()`.

## Component 2 — `discord_rpc.cpp`: minimal Discord IPC client

- **Transport:** named pipe `\\.\pipe\discord-ipc-N` for `N` in `0..9` (first that
  connects wins) on Windows. On Linux (dev only) the unix socket
  `$XDG_RUNTIME_DIR/discord-ipc-N`.
- **Framing:** 4-byte little-endian opcode + 4-byte little-endian length + JSON body.
  Opcodes: 0 handshake, 1 frame.
- **Handshake:** op 0, body `{"v": 1, "client_id": "<RAKUSPACE_DISCORD_APP_ID>"}`.
- **Set activity:** op 1, body
  `{"cmd":"SET_ACTIVITY","nonce":"<uuid>","args":{"pid":<getpid>,"activity":{...}}}`.
- **Clear activity:** same as above with `"activity": null`.
- **Lifecycle:** connect + handshake + one SET_ACTIVITY on go-live; one clear + close
  on stop. No reconnect loop, no keepalive, no response parsing beyond detecting the
  pipe closed. If no pipe is present (Discord not running), all calls silently
  no-op. Two writes per stream session, so Discord's ~5-per-20s rate limit is never
  a concern.
- **JSON:** payloads are small and fully controlled; build them with a tiny inline
  writer or a single vendored header-only JSON lib (implementer's choice, keep it to
  one file).

## Component 3 — `plugin.cpp`: glue

`obs_module_load()` registers the service and installs
`obs_frontend_add_event_callback`.

- **`OBS_FRONTEND_EVENT_STREAMING_STARTED`:**
  1. If the active streaming service type is not ours → return.
  2. Read service settings. If `discord_enabled` is false → return.
  3. Capture `timestamps.start` = current epoch seconds.
  4. If `discord_include_title` is true: `GET {RAKUSPACE_SITE_BASE}/api/check/<username>`
     with a ~3s timeout, on a worker thread (not the frontend thread), using OBS's
     bundled libcurl (`obs-deps`).
     - If the response has `known == false` → skip Discord entirely (silently).
     - If `known == true` and `title` is a non-empty string → use it as `state`.
     - On timeout / network error / empty title → proceed with no `state` line.
  5. If `discord_include_title` is false: no HTTP call; proceed with no `state` line.
     (Username is not validated in this path — the Verify button covers that case,
     and a bad username only breaks the card's button URL, not the stream.)
  6. Build the activity payload and hand it to `discord_rpc`.
- **`OBS_FRONTEND_EVENT_STREAMING_STOPPED`:** tell `discord_rpc` to clear + close.

## The Discord card

`SET_ACTIVITY` activity object:

| Field | Value |
|---|---|
| `details` | `discord_status_text` (default `"Live on RakuSpace"`) |
| `state` | stream title from `/api/check` — **only** when `discord_include_title` is on and the fetch returned a non-empty title; otherwise omitted so the card shows one line |
| `timestamps.start` | epoch seconds captured at go-live → Discord renders "NN:NN elapsed" |
| `assets.large_image` | art-asset key `"logo"` |
| `assets.large_text` | `"RakuSpace"` |
| `buttons` | `[ { "label": "Watch Stream", "url": "{RAKUSPACE_SITE_BASE}/live/<username>" } ]` |

The "RAKUSPACE" header text comes from the Discord Application itself, not the
payload.

**Explicitly excluded:** connection-status UI, viewer count, `assets.small_image`,
join/spectate secrets, party fields, reconnect logic, offline/"was live" presence.

## RakuSpace change (`frontend/RakuSpace.py`)

Extend the existing `check_stream()` route (`/api/check/<streamname>`,
`frontend/RakuSpace.py:793`):

- Current response: `{"known": <bool>}`
- New response: `{"known": <bool>, "title": <stream_title string or null>}`
- Implementation: change the `SELECT 1` to `SELECT stream_title`, keep the existence
  check on `fetchone() is not None`, add `title` to the `jsonify`.

No new route, no auth change (endpoint is already unauthenticated), no CSRF concern
(GET). The stream title is already public on the player page, so this exposes
nothing new. Existing frontend JS callers that only read `known` are unaffected.

## Baked-in plugin constants

Documented in the plugin source and README as the edit points for a different
deployment:

- `RAKUSPACE_RTMP_INGEST` — RTMP ingest server URL (scheme + host + port + app),
  e.g. `rtmp://park.raku.party:1935/live`
- `RAKUSPACE_SITE_BASE` — `https://rakuspace.site`
- `RAKUSPACE_DISCORD_APP_ID` — from the setup step below

## Discord Application setup (one-time, done during implementation)

1. Discord Developer Portal → **New Application**, name **"RakuSpace"**.
2. **Rich Presence → Art Assets** → upload the RakuSpace logo, asset key `logo`.
3. Copy the **Application ID** into `RAKUSPACE_DISCORD_APP_ID`.

No OAuth redirect URIs, no scopes, no bot user, **no submission for review** — Rich
Presence requires none of that.

## Build, CI, and testing

- `obs-plugin-template` CMake preset build. Cross-platform-buildable; Linux job is a
  compile-check only.
- CI: Windows x64 release artifact + Linux compile-check. macOS job removed from the
  template.
- **No unit-test harness** for the OBS plugin (signed off). Verification is the
  manual test matrix below, recorded in the implementation plan and run before
  release.

### Manual test matrix

1. "RakuSpace" service appears in Settings → Stream; streaming with a valid
   username + key publishes successfully to OME and plays back at
   `/live/<username>`.
2. Switching the service dropdown to "Custom" and configuring the old way still
   works (escape hatch intact).
3. `discord_enabled` off → no Discord activity is ever set, regardless of Discord
   running.
4. `discord_enabled` on, Discord desktop running → card appears on go-live with the
   correct `details` text and `Watch Stream` button URL; clears on stream stop.
5. `discord_enabled` on, Discord desktop **not** running → stream is unaffected, no
   error surfaced.
6. `discord_include_title` on with: (a) a user who has a stream title set →
   title shows as line 2; (b) a user with no title → card shows one line;
   (c) simulated endpoint timeout → card shows one line, stream unaffected.
7. `discord_include_title` on, username that does not exist (`known:false`) →
   Discord is skipped silently, stream still goes live.
8. Verify-username button: shows ✓ for a real username, ✗ for a bogus one, and does
   not block saving either way.

## Out of scope (future, not now)

- Deriving the username server-side from the stream key (would need a new
  authenticated endpoint and more plugin↔server coordination).
- Any presence while offline, or a "last live at" card.
- Viewer count / live status in the card (would need polling + rate-limit handling).
- A dockable status panel in OBS.

---

# Revision 1 (2026-09-04): the service dropdown will not show a third-party service

> **SUPERSEDED by Revision 2.** The rtmp_custom Tools menu handoff below is
> replaced by a dock plus a plugin-owned parallel output. Kept for history.

## What we found

OBS `OBSBasicSettings::LoadServices()` builds the Settings > Stream service list
only from `rtmp_common`'s property list (from `rtmp-services/data/services.json`)
plus hardcoded WHIP and "Custom" entries. It never calls `obs_enum_service_types`.
A plugin that registers its own `obs_service_info` loads fine but is invisible in
that dropdown and its callbacks never fire. Confirmed against OBS master source and
a matching OBS forum report. This was the "verify early" risk on old Task 4.

## New shape (supersedes old Tasks 4 and parts of 5)

Drop the registered service. Drive an `rtmp_custom` service from the plugin instead.

- **No `rakuspace_service` type.** Delete `rakuspace-service.cpp` / `.hpp` and the
  `rakuspace_register_service()` call.
- **Config store:** JSON at `obs_module_config_path("config.json")`. Keys:
  `stream_key`, `username`, `discord_enabled`, `discord_include_title`,
  `discord_status_text`. Read/written with the vendored `nlohmann/json`.
- **One Tools menu item**, `obs_frontend_add_tools_menu_item("RakuSpace Stream Setup", ...)`.
  - Config file missing: write a filled template, open it with the OS handler
    (`ShellExecuteA` on Windows, `xdg-open` elsewhere), return.
  - Config file present: refuse if `obs_frontend_streaming_active()`. Else parse it,
    build an `obs_data_t` with `server` = `RAKUSPACE_RTMP_INGEST`, `key` =
    `stream_key`, `use_auth` = false. `obs_service_create("rtmp_custom",
    "rakuspace_stream", settings, NULL)` -> `obs_frontend_set_streaming_service()`
    -> `obs_frontend_save_streaming_service()` -> `obs_service_release()` our ref
    (the setter takes its own; getter is borrowed per OBS docs at tags 31.1.1 /
    32.2.2). Re-open the file so the user can adjust Discord options.
  - Parse failure: log clearly, re-open the file.
- **Settings > Stream** then shows a coherent Custom entry with the URL and key
  filled. The user never opens that page.

## Go-live glue changes (was Task 5)

Kept whole: `DiscordRpc`, `check_user`, `url_encode`, the activity payload, the
generation counter, the in-flight guard, `curl_global_*`.

Changed:
- Read Discord options from the config store, not a service settings object.
- `STREAMING_STARTED` gate: case-insensitive host compare of the active service's
  `OBS_SERVICE_CONNECT_INFO_SERVER_URL` against the host in `RAKUSPACE_RTMP_INGEST`.
  Not full-string equality (a trailing slash or hand edit would kill presence).
- No verify-username button (the panel is gone). Username is validated at go-live
  only: `known:false` skips Discord, stream is unaffected. This now applies whether
  or not `discord_include_title` is set.

## String rules (all user-facing text and docs)

No em dashes, no en dashes, no hyphen as punctuation. Short. Fragments are fine for
labels and hints. If a line needs a comma or dash to hold together it is too long.
Applies to `data/locale/en-US.ini`, `obs-plugin/README.md`, the top-level README
line, and the PR body.

## What stays from the original spec

`/api/check` returning `title` (shipped on main). The Discord card shape. The
Discord Application setup step. The baked constants. OBS 30.1 floor. Windows-only
target. No automated plugin test harness. All the deliberate exclusions.

---

# Revision 2 (2026-09-04): a dock plus a plugin-owned parallel output

## Why this changes again

Two things fell out of real testing and a source check.

1. A third-party `obs_register_service` type never shows in Settings > Stream
   (Revision 1). Confirmed.
2. `obs_service_apply_encoder_settings` is called **only** from the OBS
   frontend (`SimpleOutput::Update`, `AdvancedOutput::UpdateStreamSettings` /
   `UpdateAudioSettings` / `SetupStreaming`), against `main->GetService()`.
   `libobs/obs-output.c` never calls it. So a plugin-owned output cannot
   trigger a registered service's `apply_encoder_settings` hook. Registering
   a service buys nothing.

So: no registered service. The plugin runs its **own** output next to OBS's
normal stream, the obs-multi-rtmp pattern. A dock gives the one-button connect
UX. The plugin owns the output's start and stop signals, so Discord presence
ownership is exact with no network probe on other streams.

## New shape (supersedes Revision 1 and old Tasks 4, 5)

### Delete

`obs-plugin/src/rakuspace-service.cpp` and `.hpp`. No `obs_register_service`,
no `obs_service_info`, no `get_connect_info`, no service properties panel.

### Keep unchanged

`discord-rpc.*`, `rakuspace-http.*` (`check_user`, `url_encode`), the activity
payload shape, the generation counter, the in-flight guard, `curl_global_*`,
the URL-encoded button username.

### Component A: config store

JSON at `obs_module_config_path("config.json")`, vendored `nlohmann/json`.

```cpp
struct Config {
    std::string stream_key;
    std::string username;
    bool        discord_enabled = false;
    bool        discord_include_title = false;
    std::string discord_status_text = "Live on RakuSpace";
};
Config load_config();          // missing or bad file -> defaults, never throws
bool   save_config(const Config &);
```

Written by the settings dialog, read at go-live. Not an OBS service settings
object.

### Component B: the dock

Registered with `obs_frontend_add_dock_by_id("rakuspace_dock", "RakuSpace",
widget)`. Qt widget, built with the template's `ENABLE_QT` option (prebuilt
Qt6 per platform from `buildspec.json`). Never hand-roll Qt.

Contents:

- One button. "Go Live to RakuSpace" when idle. "Stop" while our output runs.
- A status line: `Offline`, `Live 00:12:34` (elapsed, updated by a 1s
  `QTimer`), `Reconnecting`.
- A small gear button. Opens the settings dialog.

The button starts or stops **our** output only. OBS's own Start Streaming
button still exists and still works. Two go-live controls coexist. Documented,
not hidden (OBS gives no API to hide its button).

### Component C: settings dialog

A `QDialog`, also openable from an `obs_frontend_add_tools_menu_item`
("RakuSpace Settings"). Fields:

| Field | Widget | Notes |
|---|---|---|
| Stream key | `QLineEdit`, `QLineEdit::Password` | `<userid>_<streamkey>` from `/stream_info` |
| Username | `QLineEdit` | link and title fetch only |
| Share status to Discord | `QCheckBox` | master toggle |
| Include stream title | `QCheckBox` | enabled only when the master is on |
| Status text | `QLineEdit`, default `Live on RakuSpace` | enabled only when the master is on |

OK writes `config.json` via `save_config`. Cancel discards.

### Component D: the parallel output

Created fresh on each go-live, torn down on stop.

- **Service:** `obs_service_create("rtmp_custom", "rakuspace_out_service",
  settings, nullptr)` with `server` = `RAKUSPACE_RTMP_INGEST`, `key` =
  `Config::stream_key`, `use_auth` = false.
- **Encoders: self-owned, not shared.** Read the current profile's stream
  encoder id and settings, clone them, create our own with
  `obs_video_encoder_create` / `obs_audio_encoder_create`, bind with
  `obs_encoder_set_video(venc, obs_get_video())` and
  `obs_encoder_set_audio(aenc, obs_get_audio(), 0)`. Self-owned means no
  refcount entanglement with OBS starting or stopping its own stream during
  the session. The extra encode only costs anything if the user also runs
  OBS's main stream at the same time, which RakuSpace streamers do not.
  - Source of the id and settings: the profile config from
    `obs_frontend_get_profile_config()`. Simple mode: `[SimpleOutput]
    StreamEncoder` maps to an encoder id, bitrate from `[SimpleOutput] VBitrate`
    / `ABitrate`. Advanced mode (`[AdvOut] Encoder`, settings in the profile's
    `streamEncoder.json`). The implementer confirms the exact keys against the
    installed headers and OBS source.
  - If the id cannot be resolved, fall back to `obs_x264` at CBR with the
    profile's configured video bitrate (or 6000 if that also fails) and AAC
    at 160, and `blog(LOG_WARNING, ...)` that the fallback was used.
- **B-frames:** before `obs_video_encoder_create`, on the cloned video
  settings dict, `obs_data_set_int(v, "bf", 0)` and
  `obs_data_set_int(v, "bframes", 0)`. Nothing else. No codec, no rate
  control, no bitrate, no preset, no profile. `blog(LOG_INFO, ...)` one line
  saying B-frames were set to 0. No dialog, no modal.
- **Output:** `obs_output_create("rtmp_output", "rakuspace_out", nullptr,
  nullptr)`. Attach service and encoders. Turn on the output's built-in
  reconnect (`obs_output_set_reconnect_settings` if present, else the
  `rtmp_output` reconnect defaults). `obs_output_start`.

### Component E: signal handling

The output's `start`, `stop`, `reconnect`, `reconnect_success` signals fire
on **libobs threads, not the Qt thread**. Every dock update from a handler
goes through `QMetaObject::invokeMethod(dockWidget, [...]{...},
Qt::QueuedConnection)`. Touching a widget directly from a signal handler is a
crash.

| Signal | Status line | Discord | Notes |
|---|---|---|---|
| `start` | `Live 00:00:00`, start the 1s timer | push activity | generation++ |
| `reconnect` | `Reconnecting` | leave as is | |
| `reconnect_success` | back to `Live ...` | leave as is | |
| `stop` | `Offline`, stop the timer | clear activity | read `calldata_get_int(cd, "code")` for the log line only; the card clears on any stop |

`rtmp_output` handles reconnect internally, so `stop` only fires on a real
stop, whether clean or after it gives up. The card clears on every `stop`.

### Component F: Discord presence off our signals

No `OBS_FRONTEND_EVENT_STREAMING_*` for presence any more. The generation
counter, the detached worker, the `g_inflight` counter, and the bounded spin
in `obs_module_unload` all carry over. They matter more here: the clear now
runs on a libobs output-stop thread, so a blocked Discord pipe write could
wedge OBS shutdown. `discord-rpc` gets a short send and receive timeout
(non-blocking socket or a low `SO_SNDTIMEO` / `SO_RCVTIMEO`, a few hundred ms)
so a wedged Discord never blocks a libobs thread. This also closes the
deferred "pipe I/O could hang" item.

### Component G: unload

`obs_module_unload`:

- If our output is running, `obs_output_stop`, wait bounded for it to end,
  then force it if needed.
- Release output, then encoders, then service, in that order.
- Existing teardown: `obs_frontend_remove_event_callback` if any remain,
  `curl_global_cleanup`, the bounded `g_inflight` spin.
- The dock widget is owned by OBS after `add_dock_by_id`; do not free it.

## Build and CI

- Flip the template's `ENABLE_QT` to on in the presets. The template pulls
  prebuilt Qt6 from `buildspec.json` per platform. Do not add a bare
  `find_package(Qt6)` of your own.
- Linux build stays a compile check. Windows build is the real target, run by
  the user on the VM.
- Still no automated plugin test harness.

## Manual test matrix (replaces items 1, 2, 8 of the original)

1. Dock "RakuSpace" appears. Button reads "Go Live to RakuSpace", status
   "Offline".
2. Gear opens the settings dialog. Enter key and username, enable Discord,
   set status text, OK. Reopen: values persisted.
3. Click the button with a valid key. Our output connects to OME, playback
   works at `/live/<username>`. Status shows "Live" with a running timer.
   Button reads "Stop".
4. Click "Stop". Output ends, status "Offline", button resets.
5. OBS's own Settings > Stream is unchanged the whole time. Starting OBS's own
   stream separately still works.
6. `discord_enabled` off. Go live via the dock. No card.
7. `discord_enabled` on, Discord running. Go live. Card shows the status text
   and a Watch button at `rakuspace.apps.raku.party/live/<username>`. Stop.
   Card clears.
8. `discord_enabled` on, Discord not running. Go live. Stream fine, no error.
9. `discord_include_title` on, real title. Line 2 shows the title. No title
   or a timeout: one line.
10. Bad username. No card. Stream still goes live.
11. Pull the network mid-stream. Status shows "Reconnecting". Restore. Back to
    "Live", card unchanged. Kill it for good. Status "Offline", card clears.
12. Close OBS while live. It exits without hanging.

## String rules

Unchanged from Revision 1. No em dashes, no en dashes, no hyphen as
punctuation. Short. Fragments fine for labels and hints. Applies to every Qt
string, `data/locale/en-US.ini`, `obs-plugin/README.md`, the top-level README
line, the PR body.

## What stays from earlier revisions

`/api/check` returning `title` (on main). The Discord card shape and the
activity fields. The Discord Application setup step. The baked constants
(`rakuspace-config.h`). OBS 30.1 floor. Windows-only tested target. No
automated plugin test harness. Every deliberate exclusion (no viewer count,
no connection-status UI, no offline card).

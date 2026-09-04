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

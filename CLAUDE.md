# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

RakuSpace: a small Flask app that fronts OvenMediaEngine (OME) streams with OvenPlayer, plus basic user/stream-key management via an OME AdmissionWebhook. There's no separate backend service — `backend/` only holds sample OME `Server.xml` configs for reference; all application code lives in `frontend/`.

## Setup and running

```
cd frontend
python -m venv python_modules
source python_modules/bin/activate
pip install -r requirements.txt
cp rakuspace.cfg.example rakuspace.cfg   # then edit values
python setup_db.py                       # creates users.db, refuses to overwrite an existing one
python RakuSpace.py                      # runs Flask's debug server on SITE_HOST:SITE_PORT
```

Tests live in `frontend/tests/` (pytest, run `python -m pytest tests/` from `frontend/` inside the venv). No linter or build step is configured.

Production runs via granian instead of the Flask debug server (see `frontend/Containerfile`):
```
granian --host 0.0.0.0 --port 6868 --interface wsgi RakuSpace:app
```

Podman quadlet deployment: `frontend/rakuspace.container` bind-mounts `rakuspace.cfg` and `users.db` into the container; install to `~/.config/containers/systemd/` or `/etc/containers/systemd/` and reload systemd.

`rakuspace.cfg` and `*.db` are gitignored — never commit real config or the user database. `rakuspace.cfg.example` is the template for all config keys (OME hosts/ports, `SITE_HOST`/`SITE_PORT`, `DB_PATH`, `SECRET_KEY`, `BASICAUTH_ENABLED`, go-live notification settings). `SECRET_KEY` must be set to a real random value per deployment — it signs the session cookie and CSRF tokens.

## Architecture

Everything is one Flask app: `frontend/RakuSpace.py`. Key pieces:

- **Auth model**: there's no login system of its own. `require_auth` reads the username from `X-Forwarded-User`/`Remote-User` headers (set by an upstream reverse-proxy auth layer like Authelia) or, if `BASICAUTH_ENABLED` is true, decodes HTTP Basic auth. Routes decorated with `@require_auth` receive the resolved `username` as a kwarg. Basic auth here only ever reads the *username* out of the credentials — the password is decoded and discarded, deliberately, as a zero-setup way to switch users locally without standing up a real auth layer; never enable `BASICAUTH_ENABLED` outside a machine only the developer can reach.
- **CSRF**: `Flask-WTF`'s `CSRFProtect` wraps the app; state-changing POST routes (`regen_key`, `save_settings`, `set_notifications`, `test_notification`) need a `csrf_token` hidden field, already present in `stream.html`/`notifications.html`. `/auth/ome` is `@csrf.exempt` since OME calls it directly, not a browser.
- **User/key storage**: a single SQLite table (`users`, see `setup_db.py`) keyed by `userid`/`username`, storing a per-user `streamkey` (random 30-char token via `generate_stream_key`), `stream_title`, `offline_image_url`, and the go-live notification columns below. `get_db()`/`close_db()` manage a per-request connection via Flask's `g`. `ensure_schema()` runs at import time and idempotently `ALTER TABLE ADD COLUMN`s any notification columns missing from an older `users.db`, so existing deployments don't need a manual migration; `setup_db.py` already creates the full schema for fresh databases. Usernames are always lowercase: `normalize_username()` runs on every entry point (auth headers, `/live/<name>` which redirects to lowercase, SSE, `/api/check`, and the frontend inputs), and `ensure_schema()` also lowercases older stored usernames via `lowercase_usernames()`, logging any that collide for a manual merge.
- **OME integration is the core flow**: OME is configured with `AdmissionWebhooks` pointing at `POST /auth/ome` (see `backend/README.md` and `Server.xml*`). When a user's streaming client publishes RTMP to `.../live/<userid>_<streamkey>`, OME calls this webhook; `verify_webhook()` parses the URL, validates hostname against `OME_PROVIDER_HOST`/`RTMP_ALT_HOSTS`, looks up the user by `userid`, and compares `streamkey` with `secrets.compare_digest`. On success it returns `new_url` rewriting the stream to `RTMP_HOST/<username>`, which is what viewers/players actually reference. Publish (`opening`) and unpublish (`closing`) events also feed `_set_notify_state`/`_set_live_state` (see below); the `closing` path is best-effort and never denies/errors on malformed input, since it isn't an auth decision.
- **Live-state push**: `_set_live_state`/`_get_live_state` track each username's `"live"`/`"offline"` state in memory, updated directly off the webhook's opening/closing events. `/api/live/<streamname>/events` exposes this as Server-Sent Events (via a `threading.Condition`) so player pages update instantly instead of polling. In-memory and single-process — a multi-worker deployment would need a shared store instead.
- **Go-live/offline notifications**: `notify_on_live`/`notify_on_offline` gate whether a user wants notifications at all; the actual send target is either a generic webhook (`notify_url`, POSTed a JSON payload) or, if `notify_builtin` is set, the built-in Discord/IRC senders (`_send_discord`/`_send_irc`) configured per-user as JSON in `notify_config` (edited via `/settings/notifications`, parsed/defaulted by `_parse_notify_config`/`_load_notify_config`/`_default_notify_config`). Webhook opening/closing events only update in-memory `_notify_state`; a daemon thread (`_notify_reconciler`, started at import time) polls every `NOTIFY_TICK_SECONDS` and only actually sends once a user's state has been stable for `NOTIFY_SETTLE_SECONDS` (going live) or the longer `NOTIFY_OFFLINE_GRACE_SECONDS` (going offline) — the longer offline grace means a brief drop/reconnect (e.g. an OME restart) never fires an offline notification and isn't treated as a fresh stream start either, debouncing rapid reconnect/restart flapping into a single notification. `_validate_notify_url`/`_irc_host_blocked` apply a best-effort SSRF guard (scheme + private/loopback/localhost checks, optional admin hostname whitelist) to user-supplied notify URLs and IRC servers — judged sufficient for this app's scope, not a general-purpose URL fetcher's defenses.
- **Pages**:
  - `/` — generic landing page that lets you jump to `/live/<name>` (OvenPlayer view), `/multistream`, or `/settings`.
  - `/live/<streamname>` — public player page (`player.html`) wired to `OME_PUBLISHER_HOST`/`PORT`/`OME_APP_NAME` for WebRTC playback, plus the offline image if configured for that user.
  - `/multistream` — multi-tile stream viewer. Default is a conference style view (`multistream.html`): the pinned stream focused at 16:9 with the rest in a scrolling bottom strip, or a 16:9 grid when nothing is pinned; state in localStorage `rakuspace-multistream-v1`. `?advanced=1` serves the old free form split layout (`multistream_advanced.html`), and each links to the other from its burger menu. Only tiles that change container reload, since moving an iframe reloads it.
  - `/settings` (auth required) — shows/creates the caller's stream key and RTMP URL(s), plus stream title/offline image/notification settings (`stream.html`); `/settings/regen_key` and `/settings/save_settings` are the POST actions on this page. Old `/stream_info` paths 308 redirect here (`legacy_stream_info`) so history and bookmarks keep working.
  - `/settings/notifications` (auth required) — per-user Discord/IRC notification config (`notifications.html`); GET renders it, POST is `set_notifications`. `/settings/notifications/test` POSTs a one-off test notification through the same channel without saving.
  - `/auth/ome` — the AdmissionWebhook target described above; not user-facing.
  - `/api/check/<streamname>` — small JSON existence check used by the frontend JS.
  - `/api/live/<streamname>/events` — SSE live-state stream described above.
- Config is loaded once at import time from `rakuspace.cfg` via `app.config.from_pyfile`; all the `OME_*`/`SITE_*`/`DB_PATH`/`NOTIFY_*` globals near the top of `RakuSpace.py` are derived from that at startup, not re-read per request.

## Working in this repo

- Templates (`frontend/templates/*.html`) and `frontend/static/` (bundled OvenPlayer) are the actual frontend. Stale scratch artifacts (old drafts, a stray zip) live tucked away in `old/` folders next to whatever they're a stale copy of (`frontend/old/`, `frontend/templates/old/`, top-level `old/`) — not part of the served app, don't treat them as sources of truth.
- `backend/Server.xml*` files are illustrative OME configs ("probably won't even launch without modification" per `backend/README.md`), not a runnable service to build against.

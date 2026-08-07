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

There is no test suite, linter, or build step configured in this repo.

Production runs via granian instead of the Flask debug server (see `frontend/Dockerfile`):
```
granian --host 0.0.0.0 --port 6868 --interface wsgi RakuSpace:app
```

Podman quadlet deployment: `frontend/rakuspace.container` bind-mounts `rakuspace.cfg` and `users.db` into the container; install to `~/.config/containers/systemd/` or `/etc/containers/systemd/` and reload systemd.

`rakuspace.cfg` and `*.db` are gitignored — never commit real config or the user database. `rakuspace.cfg.example` is the template for all config keys (OME hosts/ports, `SITE_HOST`/`SITE_PORT`, `DB_PATH`, `BASICAUTH_ENABLED`).

## Architecture

Everything is one Flask app: `frontend/RakuSpace.py`. Key pieces:

- **Auth model**: there's no login system of its own. `require_auth` reads the username from `X-Forwarded-User`/`Remote-User` headers (set by an upstream reverse-proxy auth layer like Authelia) or, if `BASICAUTH_ENABLED` is true, decodes HTTP Basic auth. Routes decorated with `@require_auth` receive the resolved `username` as a kwarg.
- **User/key storage**: a single SQLite table (`users`, see `setup_db.py`) keyed by `userid`/`username`, storing a per-user `streamkey` (random 30-char token via `generate_stream_key`) and `stream_title` set through the app. `get_db()`/`close_db()` manage a per-request connection via Flask's `g`.
- **OME integration is the core flow**: OME is configured with `AdmissionWebhooks` pointing at `POST /auth/ome` (see `backend/README.md` and `Server.xml*`). When a user's streaming client publishes RTMP to `.../live/<userid>_<streamkey>`, OME calls this webhook; `verify_webhook()` parses the URL, validates hostname against `OME_PROVIDER_HOST`/`RTMP_ALT_HOSTS`, looks up the user by `userid`, and compares `streamkey` with `secrets.compare_digest`. On success it returns `new_url` rewriting the stream to `RTMP_HOST/<username>`, which is what viewers/players actually reference.
- **Pages**:
  - `/` — generic landing page that lets you jump to `/live/<name>` (OvenPlayer view) or `/stream_info`.
  - `/live/<streamname>` — public player page (`player.html`) wired to `OME_PUBLISHER_HOST`/`PORT`/`OME_APP_NAME` for WebRTC playback.
  - `/stream_info` (auth required) — shows/creates the caller's stream key and RTMP URL (`stream.html`); `/stream_info/regen_key` and `/stream_info/set_title` are POST actions on this page.
  - `/auth/ome` — the AdmissionWebhook target described above; not user-facing.
  - `/api/check/<streamname>` — small JSON existence check used by the frontend JS.
- Config is loaded once at import time from `rakuspace.cfg` via `app.config.from_pyfile`; all the `OME_*`/`SITE_*`/`DB_PATH` globals near the top of `RakuSpace.py` are derived from that at startup, not re-read per request.

## Working in this repo

- Templates (`frontend/templates/*.html`) and `frontend/static/` (bundled OvenPlayer) are the actual frontend; files suffixed `.old`/`.v2` or the top-level loose `index.html`/`rakuspace.zip` are stale scratch artifacts, not part of the served app — don't treat them as sources of truth.
- `backend/Server.xml*` files are illustrative OME configs ("probably won't even launch without modification" per `backend/README.md`), not a runnable service to build against.

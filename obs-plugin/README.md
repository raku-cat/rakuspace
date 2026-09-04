# RakuSpace OBS plugin

## What it is

An OBS Studio plugin for [RakuSpace](https://rakuspace.site). It does two things:

- Adds a **"RakuSpace"** service to **Settings → Stream**, so you pick RakuSpace
  from the Service dropdown, paste your stream key and username, and OBS streams
  to the right RTMP ingest without you copying URLs around.
- Optionally shows a **Discord Rich Presence** card while you are live: your
  stream title, a link button back to your RakuSpace page, and an elapsed timer.

Requires **OBS Studio 30.1 or newer**. Built and shipped for **Windows x64**;
Linux is a compile-check target only (see *Build from source*).

## Install (Windows)

1. Download the latest Windows build from the repository **Releases** page, or
   from the **CI artifacts** of a successful `Build Project` run.
2. Run the installer, **or** unzip the archive into
   `%ProgramData%\obs-studio\plugins\`.
3. Restart OBS Studio.

## Use

1. **Settings → Stream**.
2. **Service** → **RakuSpace**.
3. Paste the **Stream Key** shown on your RakuSpace `stream_info` page.
4. Type your **RakuSpace username** (the name your channel lives at, e.g.
   `rakuspace.site/live/<username>`).
5. Optionally use the **Verify** button to check the username against the site.
6. Optionally tick **"Share status to Discord"** (and, nested under it, whether
   to include your stream title in the Discord card).

That is the whole surface. There is no connection-status readout, no viewer
count, no reconnect handling, and no "stream offline" card — by design.

## Pointing it at another deployment

Three constants in [`src/rakuspace-config.h`](src/rakuspace-config.h) are the
only values to change for a different RakuSpace / OME deployment:

- **`RAKUSPACE_RTMP_INGEST`** — scheme + host + port + OME app name, no trailing
  slash. Must match what `/stream_info` shows as the "RTMP URL"
  (currently `rtmp://park.raku.party:1935/rakuspace`).
- **`RAKUSPACE_SITE_BASE`** — public site base, no trailing slash. Used for the
  `/api/check` username lookup and the `/live` link button
  (currently `https://rakuspace.site`).
- **`RAKUSPACE_DISCORD_APP_ID`** — the Discord Application ID for the Rich
  Presence card (see below). **Currently the placeholder
  `REPLACE_WITH_REAL_DISCORD_APP_ID`** — the Discord integration is inert until
  this is filled in with a real ID.

Change these, rebuild, redistribute.

## Discord Application setup (one-time)

The Rich Presence card needs a Discord Application ID. There is **no OAuth, no
scopes, and no app review** involved — Rich Presence just needs the numeric ID
and its uploaded art.

1. Open the [Discord Developer Portal](https://discord.com/developers/applications).
2. **New Application**, name it **"RakuSpace"**.
3. **Rich Presence → Art Assets** → upload the RakuSpace logo as an asset with
   the key **`logo`** (the plugin references `large_image: "logo"`).
4. Copy the **Application ID** from the app's **General Information** page into
   `RAKUSPACE_DISCORD_APP_ID` in `src/rakuspace-config.h`, then rebuild.

## Build from source

```
cmake --preset windows-x64     # Windows x64
cmake --preset ubuntu-x86_64   # Linux compile-check
cmake --build --preset windows-x64      # or ubuntu-x86_64
```

Optional standalone Discord check (not part of the plugin, no libobs needed):

```
cmake --preset ubuntu-x86_64 -DRAKUSPACE_BUILD_SMOKE=ON
cmake --build --preset ubuntu-x86_64 --target rpc-smoke
./rpc-smoke        # sends one SET_ACTIVITY to a running Discord, then clears it
```

### Note on `curl` on Windows CI

`buildspec.json` does **not** pin `curl` in its `dependencies`. The CMake build
uses `find_package(CURL)` and is expected to resolve libcurl from the OBS
prebuilt dependencies bundle on the Windows runner. This has not yet been
confirmed against a real Windows CI run — verify it on the first CI build and
add an explicit dependency pin if it does not resolve.

## Status

The **full manual test matrix on Windows has not been run** (it needs a Windows
box with OBS 30.1+, Discord desktop, a live OME ingest, and a real streamer
key). `RAKUSPACE_DISCORD_APP_ID` is **still the placeholder** noted above; the
Discord Rich Presence path is wired but untested end to end until a real
Application ID is in place.

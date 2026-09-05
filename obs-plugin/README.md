# RakuSpace OBS plugin

Shows a Discord Rich Presence card while you stream to RakuSpace. Needs OBS 30.1 or newer.

## Install

Unzip into the OBS plugins folder. Restart OBS.

## Setup

Open the RakuSpace dock. Click Settings. Enter your stream key and username from `/stream_info`. Tick Share status to Discord if you want the card. OK.

## Go live

Click Go Live to RakuSpace in the dock. Click Stop to end it. OBS's own Start Streaming is separate and still works.

## Config keys

File at the plugin config path, `config.json`.

- `stream_key`: your RakuSpace stream key.
- `username`: your RakuSpace username.
- `discord_enabled`: show the Rich Presence card.
- `discord_include_title`: put your stream title on line 2.
- `discord_status_text`: the text on line 1.

## Encoder

Uses your OBS stream encoder settings. Forces B-frames to 0 for OME low latency. Nothing else changed.

## Deployment constants

In `src/rakuspace-config.h`.

- `RAKUSPACE_RTMP_INGEST`
- `RAKUSPACE_SITE_BASE`
- `RAKUSPACE_DISCORD_APP_ID`

## Discord app

Developer Portal. New Application. Rich Presence. Art Assets. Upload a logo with key `logo`. Copy the Application ID into the constant. No OAuth. No review.

## Build

```
cmake --preset windows-x64
cmake --build --preset windows-x64 --config RelWithDebInfo
```

Optional `-DRAKUSPACE_BUILD_SMOKE=ON` builds `rpc-smoke`.

Logs the git short hash on load (`[rakuspace-obs] loaded, build <hash>`). Check
the OBS log against `git rev-parse --short=10 HEAD` to confirm a rebuilt
plugin actually replaced the loaded one.

## Scope

No viewer count. No connection status readout beyond the dock. No offline card.

The activity is set to Watching so the card logic has a real type, but
Discord's local RPC connection ignores it for the member list line, which
still reads "Playing RakuSpace." Only the big card (details, state, image,
button) is real. This is a known Discord limitation, not something we can
fix from here. If Discord ever honors it, the member list line will start
reading "Watching RakuSpace" with no code change needed.

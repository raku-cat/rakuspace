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

## Scope

No viewer count. No connection status readout beyond the dock. No offline card.

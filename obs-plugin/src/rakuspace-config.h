#pragma once

/*
 * Deployment-specific constants. These are the only values to change when
 * pointing this plugin at a different RakuSpace / OME deployment.
 */

/* RTMP ingest: scheme + host + port + OME app name, no trailing slash.
 * Must match what /stream_info shows as the "RTMP URL".
 * Derived from frontend/rakuspace.cfg:
 *   OME_PROVIDER_HOST=park.raku.party
 *   OME_RTMP_PROVIDER_PORT=1935
 *   OME_APP_NAME=rakuspace
 */
#define RAKUSPACE_RTMP_INGEST "rtmp://live.rakuspace.on.omusubi.trans:1935/rakuspace"

/* Public site base, no trailing slash. Used for /api/check and /live links. */
#define RAKUSPACE_SITE_BASE "https://rakuspace.apps.raku.party"

/* Discord Application ID from the Developer Portal (Rich Presence). */
#define RAKUSPACE_DISCORD_APP_ID "1413929830055153898"

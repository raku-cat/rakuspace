# RakuSpace Backend

Three barebones sample OvenMediaEngine configs with the necessary settings to work with the flask app to use as reference.
These configs probably wont even launch if used without modification.

The important section is:
```
<AdmissionWebhooks>
	<ControlServerUrl>http://0.0.0.0:6868/auth/ome</ControlServerUrl>
	<Timeout>3000</Timeout>
	<Enables>
		<Providers>rtmp webrtc</Providers>
	</Enables>
</AdmissionWebhooks>
```

The rest just configures the server with a WebRTC publisher as needed by OvenPlayer, an RTMP
provider for external clients (OBS etc), and a WebRTC provider for WHIP (WebRTC-HTTP
Ingestion Protocol) ingest, used by RakuSpace's in-browser "Go Live!" screenshare page
(`/go_live`). `verify_webhook()` in `RakuSpace.py` authorizes a publish purely by parsing
`<userid>_<streamkey>` off the end of the publish URL and checking the hostname -- it doesn't
care whether the transport was RTMP or WHIP, so no app-side changes were needed to support
WHIP; OME just needs the `webrtc` provider enabled here and a `<WebRTC>` block under
`<Providers>` (see `Server.xml`/`Server.xml_Origin`) so there's something to publish *to*.

The WHIP ingest and the WebRTC playback publisher share the same signalling `TLSPort` (3334)
and ICE candidate/TCP relay config -- no separate port is needed. RakuSpace's `OME_WHIP_URL`
config value (see `rakuspace.cfg.example`) should point at `https://<host>:<TLSPort>/<app-name>`
for whichever host has the `webrtc` provider enabled.


## Origin/Edge configuration
Though not in any way necessary, the files `Server.xml_Origin` and `Server.xml_Edge` provide a sample configuration needed to run an edge instance and origin instance of OME instead of having the provider and publisher on one instance. The WebRTC/WHIP *provider* (ingest) belongs on the origin (alongside RTMP) since that's where publishes land; `Server.xml_Edge` stays playback-only and doesn't need it.

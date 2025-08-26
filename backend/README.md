# RakuSpace Backend

Three barebones sample OvenMediaEngine configs with the necessary settings to work with the flask app to use as reference.
These configs probably wont even launch if used without modification.

The important section is:
```
<AdmissionWebhooks>
	<ControlServerUrl>http://0.0.0.0:6868/verify</ControlServerUrl>
	<Timeout>3000</Timeout>
	<Enables>
		<Providers>rtmp</Providers>
	</Enables>
</AdmissionWebhooks>
```

The rest just configures the server with a WebRTC publisher as needed by OvenPlayer, and an RTMP provider.


## Origin/Edge configuration
Though not in any way necessary, the files `Server.xml_Origin` and `Server.xml_Edge` provide a sample configuration needed to run an edge instance and origin instance of OME instead of having the provider and publisher on one instance.

# RakuSpace Frontend

A small flask app serving OvenPlayer instances for named OME streams, and basic user/stream key management when used as an AdmissionWebhook in OME.

## Running/Installation
To get started, you'll need to install the required pypi dependencies, modify the config to your liking, generate an empty user db, and then run the app. 
By default this will have you running with flask's built in server, but you should probably use something like granian which this ships with by default, refer to [Containerfile](/Containerfile) for a usage example.
```
$ git clone https://github.com/raku-cat/rakuspace.git && cd rakuspace/frontend
$ python -m venv python_modules
$ source python_modules/bin/activate
(python_modules) $ pip install -r requirements.txt
(python_modules) $ cp rakuspace.cfg{.example,}
(python_modules) $ python setup_db.py
(python_modules) $ python RakuSpace.py
```
With the default config, you should now have the app available at http://localhost:5000.

## Endpoints
The app wont do much on its own, it has the following pages:
 - `/`
  - Displays an input field to direct you to `/live/<name>`, which will load an OvenPlayer instance that points to the stream with that name under the app specified in the config, or to `/multistream`.
 - `/live/<streamname>`
  - Public OvenPlayer view for a given stream name, with an offline image if that user has configured one.
 - `/multistream`
  - Multi-tile stream viewer. One stream focused with the rest in a strip along the bottom, or a grid. Pin a tile to focus it. `?advanced=1` gives the older free form split layout.
 - `/stream_info`
  - Expects to be accessed through something like Authelia or, if you enabled it, http basic auth. It will read the username from the relevant authentication header, and create a database entry for that user, displaying the key and rtmp endpoint(s) to use, with buttons to regenerate the key and set a stream title, offline image, and go-live/offline notification settings.
 - `/stream_info/regen_key`, `/stream_info/save_settings`
  - POST-only actions used by the `/stream_info` page.
 - `/stream_info/notifications`
  - Per-user configuration for the built-in Discord and IRC go-live/offline notifiers (as an alternative to a generic webhook URL set on `/stream_info`).
 - `/stream_info/notifications/test`
  - POST-only action that sends a one-off test notification through the configured Discord/IRC channel without saving.
 - `/auth/ome`
  - To be used with OME's AdmissionWebhook to authenticate stream keys, see configs in [backend](https://github.com/raku-cat/rakuspace/backend) for more information on how to set this up.
 - `/api/check/<streamname>`
  - Small JSON existence check (`{"known": true/false}`) used by the frontend JS on `/`.
 - `/api/live/<streamname>/events`
  - Server-Sent Events stream of a user's live/offline state, used to update player pages instantly.

## Running with podman
An example podman quadlet is also provided which bind mounts user.db and the config file to a location in the host filesystem, it'll need to be edited before use, and then placed in either `~/.config/containers/systemd/` or `/etc/containers/systemd/`, after a `daemon-reload` you can then start rakuspace.service as a user or system service like any other service.

## Screenshots
To be filled in


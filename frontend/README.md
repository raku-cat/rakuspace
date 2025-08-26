# RakuSpace Frontend

A small flask app serving OvenPlayer instances for named OME streams, and basic user/stream key management when used as an AdmissionWebhook in OME.

## Running/Installation
To get started, you'll need to install the required pypi dependencies, modify the config to your liking, generate an empty user db, and then run the app. 
By default this will have you running with flask's built in server, but you should probably use something like granian which this ships with by default, refer to [Dockerfile](/Dockerfile) for a usage example.
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
  - Displays an input field to direct you to a sub-path of anything you enter, which for anything but `/stream`, will load an OvenPlayer instance that points to the stream with the same name under the app specified in the config. If that's all you want, you're done!
 - `/stream`
  - Expects to be accessed through something like Authelia or, if you enabled it, http basic auth. It will read the username from the relevant authentication header, and create a databse entry for that user, displaying the key and rtmp endpoint to use, with a button to regenerate the key.
 - `/verify` 
  - To be used with OME's AdmissionWebhook to authenticate stream keys, see configs in [backend](https://github.com/raku-cat/rakuspace/backend) for more information on how to set this up.

## Running with podman
An example podman quadlet is also provided which bind mounts user.db and the config file to a location in the host filesystem, it'll need to be edited before use, and then placed in either `~/.config/containers/systemd/` or `/etc/containers/systemd/`, after a `daemon-reload` you can then start rakuspace.service as a user or system service like any other service.

## Screenshots
To be filled in


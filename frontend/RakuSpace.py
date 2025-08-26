import base64
import sqlite3
import secrets
import string
from functools import wraps
from flask import Flask, request, g, render_template, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit


app = Flask(__name__)
socketio = SocketIO(app)
app.config.from_pyfile('rakuspace.cfg')

# --- Initialize config values ---
DB_PATH = app.config['DB_PATH']
OME_PROVIDER_HOST = app.config['OME_PROVIDER_HOST']
OME_PUBLISHER_HOST = app.config['OME_PUBLISHER_HOST']
OME_PUBLISHER_PORT = app.config['OME_PUBLISHER_PORT']
OME_APP_NAME = app.config['OME_APP_NAME']
OME_RTMP_PROVIDER_PORT = app.config['OME_RTMP_PROVIDER_PORT']
RTMP_HOST = f"rtmp://{OME_PROVIDER_HOST}:{OME_RTMP_PROVIDER_PORT}/{OME_APP_NAME}"


# --- DB helpers ---
def get_db():
    db = getattr(g, "_db", None)
    if db is None:
        db = g._db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_db(exc):
    if "db" in g:
        g.db.close()


# --- User / key management ---
def get_or_create_userkey(username, regen=False):
    db = get_db()
    with db:  # automatically commits after insert
        cur = db.cursor()
        cur.execute("SELECT userid, streamkey FROM users WHERE username=?", (username,))
        row = cur.fetchone()

        if row and not regen:
            userid, streamkey = row["userid"], row["streamkey"]
        else:
            streamkey = generate_stream_key()
            if not row:
                cur.execute("INSERT INTO users (username, streamkey) VALUES (?, ?)", (username, streamkey))
                userid = cur.lastrowid
            else:
                cur.execute("UPDATE users SET streamkey=? WHERE username=?", (streamkey, username))
                userid = row["userid"]

    return userid, streamkey

def generate_stream_key(length=30):
    alphabet = string.ascii_letters + string.digits  # a-zA-Z0-9
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        header_username = (
            request.headers.get("X-Forwarded-User")
            or request.headers.get("Remote-User")
        )
        if header_username:
             username = header_username

        if eval(app.config['BASICAUTH_ENABLED']):
            auth = request.headers.get("Authorization")
            if auth and auth.startswith("Basic "):
                try:
                    import base64
                    userpass = base64.b64decode(auth.split(" ")[1]).decode()
                    basicauth_username, _ = userpass.split(":", 1)
                    username = basicauth_username
                except Exception:
                    pass
        if not username:
            abort(401)  # Unauthorized
        # Pass username to the route function as a keyword argument
        return f(username=username, *args, **kwargs)
    return decorated


# --- Routes ---
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/<streamname>")
def play_stream(streamname):
    return render_template(
        "player.html",
        streamname=streamname,
        OME_PUBLISHER_HOST=OME_PUBLISHER_HOST,
        OME_PUBLISHER_PORT=OME_PUBLISHER_PORT,
        OME_APP_NAME=OME_APP_NAME
    )


@app.route("/stream")
@require_auth
def stream_page(username):
    # In production this comes from Authelia/NGINX via REMOTE_USER header

    userid, streamkey = get_or_create_userkey(username)

    return render_template(
        "stream.html",
        username=username,
        userid=userid,
        streamkey=streamkey,
        rtmp_url=RTMP_HOST
    )

@app.route("/stream", methods=["POST"])
@require_auth
def regen_key(username):
    get_or_create_userkey(username, regen=True)
    return redirect(url_for("stream_page"))


@app.route("/verify", methods=["POST"])
def verify_webhook():
    deny = jsonify({"allowed": False})
    data = request.json
    req = data.get("request", {})
    url = req.get("url", "")
    direction = req.get("direction")
    status = req.get("status")

    # We only care about publish/open
    if direction == "incoming" and status == "opening":
        # Extract stream key from the end of the URL
        try:
            key_part = url[len(RTMP_HOST):]
            key_part = key_part.strip('/')
            userid_str, key = key_part.split("_", 1)
            userid = int(userid_str)
        except (ValueError, AttributeError):
            return deny

        # Lookup user from key
        db = get_db()
        with db:  # automatically commits after insert
            cur = db.cursor()
            cur.execute("SELECT username, streamkey FROM users WHERE userid=?", (userid,))
            row = cur.fetchone()
        if not row:
            return deny

        username, correct_key = row
        if secrets.compare_digest(correct_key, key):
            new_url = f"{RTMP_HOST}/{username}"
            response = jsonify({
                "allowed": True,
                "new_url": new_url,
                "lifetime": 0,
                "reason": "authorized"
            })
            return response
        else:
            return deny
    if status == "closing":
        return {}


# --- Debug Server ---
SITE_HOST = app.config['SITE_HOST']
SITE_PORT = app.config['SITE_PORT']
if __name__ == '__main__':
    socketio.run(app, host=SITE_HOST, port=int(SITE_PORT),
                 debug=True, use_reloader=True)

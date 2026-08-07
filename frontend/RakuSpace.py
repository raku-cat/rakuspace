import base64
import ipaddress
import json
import logging
import socket
import ssl
import sqlite3
import secrets
import string
import threading
import time
import urllib.request
from datetime import datetime, timezone
from functools import wraps
from flask import Flask, request, g, render_template, redirect, url_for, jsonify, abort
from flask_socketio import SocketIO, emit
from urllib.parse import urlparse

app = Flask(__name__)
socketio = SocketIO(app)
app.config.from_pyfile('rakuspace.cfg')

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

# --- Initialize config values ---
DB_PATH = app.config['DB_PATH']
OME_PROVIDER_HOST = app.config['OME_PROVIDER_HOST']
OME_PUBLISHER_HOST = app.config['OME_PUBLISHER_HOST']
OME_PUBLISHER_PORT = app.config['OME_PUBLISHER_PORT']
OME_APP_NAME = app.config['OME_APP_NAME']
OME_RTMP_PROVIDER_PORT = app.config['OME_RTMP_PROVIDER_PORT']
RTMP_HOST = f"rtmp://{OME_PROVIDER_HOST}:{OME_RTMP_PROVIDER_PORT}/{OME_APP_NAME}"
RTMP_ALT_HOSTS = app.config['RTMP_ALT_HOSTS']
RTMP_URLS = [RTMP_HOST] + [
    f"rtmp://{host}:{OME_RTMP_PROVIDER_PORT}/{OME_APP_NAME}"
    for host in sorted(RTMP_ALT_HOSTS)
    if host != OME_PROVIDER_HOST
]

# --- Go-live notification config ---
NOTIFY_VALIDATE_URLS = str(app.config.get('NOTIFY_VALIDATE_URLS', 'True')).lower() == 'true'
NOTIFY_URL_WHITELIST_ENABLED = str(app.config.get('NOTIFY_URL_WHITELIST_ENABLED', 'False')).lower() == 'true'
NOTIFY_URL_WHITELIST = app.config.get('NOTIFY_URL_WHITELIST', [])
NOTIFY_SETTLE_SECONDS = int(app.config.get('NOTIFY_SETTLE_SECONDS', 15))
NOTIFY_TICK_SECONDS = int(app.config.get('NOTIFY_TICK_SECONDS', 5))
NOTIFY_TIMEOUT_SECONDS = int(app.config.get('NOTIFY_TIMEOUT_SECONDS', 3))
SITE_PUBLIC_URL = app.config.get('SITE_PUBLIC_URL', '')

# --- DB helpers ---
def get_db():
    db = getattr(g, "_db", None)
    if db is None:
        db = g._db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_db(exc):
    if "_db" in g:
        g._db.close()


def ensure_schema():
    """Idempotently add notification columns to an existing users.db so older
    deployments don't need to manually migrate. setup_db.py already creates
    these columns for fresh databases."""
    notify_columns = {
        "notify_url": "TEXT",
        "notify_builtin": "INTEGER NOT NULL DEFAULT 0",
        "notify_on_live": "INTEGER NOT NULL DEFAULT 1",
        "notify_on_offline": "INTEGER NOT NULL DEFAULT 0",
        "notify_config": "TEXT",
    }
    db = sqlite3.connect(DB_PATH)
    try:
        existing = {row[1] for row in db.execute("PRAGMA table_info(users)")}
        for column, ddl_type in notify_columns.items():
            if column not in existing:
                db.execute(f"ALTER TABLE users ADD COLUMN {column} {ddl_type}")
        db.commit()
    finally:
        db.close()


ensure_schema()


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
        username = None

        header_username = (
            request.headers.get("X-Forwarded-User")
            or request.headers.get("Remote-User")
        )
        if header_username:
             username = header_username

        if str(app.config['BASICAUTH_ENABLED']).lower() == 'true':
            auth = request.headers.get("Authorization")
            if auth and auth.startswith("Basic "):
                try:
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


# --- Go-live notifications ---
# OME's open/close events only update in-memory state here; a background
# reconciler thread is the only thing that actually sends notifications, once
# a user's state has been stable for NOTIFY_SETTLE_SECONDS. This debounces
# flapping connections (rapid reconnect/restart) into a single notification
# instead of spamming the target URL on every OME event.
_notify_lock = threading.Lock()
_notify_state = {}  # userid -> {"state": "live"|"offline", "changed_at": ts, "notified_state": ...}

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _set_notify_state(userid, state):
    with _notify_lock:
        entry = _notify_state.get(userid)
        if entry is None or entry["state"] != state:
            _notify_state[userid] = {
                "state": state,
                "changed_at": time.monotonic(),
                "notified_state": entry["notified_state"] if entry else None,
            }


def _validate_notify_url(url):
    """Returns None if the URL is acceptable, or an error string otherwise.
    Best-effort SSRF guard: hostname allow/deny checks don't stop DNS
    rebinding, but this is a small self-hosted app, not a general-purpose
    URL fetcher, so this is judged sufficient for the scope."""
    if not url:
        return None  # empty is fine, it just means notifications are off

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return "URL must be a valid http:// or https:// URL."

    hostname = parsed.hostname

    if NOTIFY_VALIDATE_URLS:
        if hostname == "localhost":
            return "URL may not target localhost."
        try:
            ip = ipaddress.ip_address(hostname)
        except ValueError:
            ip = None
        if ip is not None and any(ip in net for net in _PRIVATE_NETWORKS):
            return "URL may not target a private or loopback address."

    if NOTIFY_URL_WHITELIST_ENABLED and hostname not in NOTIFY_URL_WHITELIST:
        return f"URL host '{hostname}' is not in the configured whitelist."

    return None


def _default_notify_config():
    return {
        "discord": {
            "enabled": False,
            "webhook_url": "",
            "online": {"content": "", "title": "{username} is live!", "description": "{title}", "color": "#57F287"},
            "offline": {"content": "", "title": "{username} is offline", "description": "", "color": "#808080"},
        },
        "irc": {
            "enabled": False,
            "server": "", "port": 6697, "tls": True,
            "server_password": "", "sasl_user": "", "sasl_password": "",
            "nick": "", "channel": "",
            "online": {"body": "{username} is now live: {title} {url}"},
            "offline": {"body": "{username} has gone offline"},
        },
    }


def _load_notify_config(raw):
    """Parses the notify_config JSON column, deep-merged over the defaults so
    missing keys (new fields, older saved configs) always resolve."""
    cfg = _default_notify_config()
    if not raw:
        return cfg
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return cfg
    for channel in ("discord", "irc"):
        channel_cfg = parsed.get(channel)
        if not isinstance(channel_cfg, dict):
            continue
        for key, value in channel_cfg.items():
            if key in ("online", "offline") and isinstance(value, dict):
                cfg[channel][key].update(value)
            else:
                cfg[channel][key] = value
    return cfg


def _parse_notify_config(form):
    """Builds a notify_config dict from a submitted form. Shared by the save
    route and the test-send route so parsing only lives in one place."""
    def discord_block(prefix):
        return {
            "content": (form.get(f"discord_{prefix}_content") or "").strip(),
            "title": (form.get(f"discord_{prefix}_title") or "").strip(),
            "description": (form.get(f"discord_{prefix}_description") or "").strip(),
            "color": (form.get(f"discord_{prefix}_color") or "").strip(),
        }

    def irc_block(prefix):
        return {"body": (form.get(f"irc_{prefix}_body") or "").strip()}

    try:
        irc_port = int(form.get("irc_port") or 6697)
    except ValueError:
        irc_port = 6697

    return {
        "discord": {
            "enabled": form.get("discord_enabled") == "on",
            "webhook_url": (form.get("discord_webhook_url") or "").strip(),
            "online": discord_block("online"),
            "offline": discord_block("offline"),
        },
        "irc": {
            "enabled": form.get("irc_enabled") == "on",
            "server": (form.get("irc_server") or "").strip(),
            "port": irc_port,
            "tls": form.get("irc_tls") == "on",
            "server_password": form.get("irc_server_password") or "",
            "sasl_user": (form.get("irc_sasl_user") or "").strip(),
            "sasl_password": form.get("irc_sasl_password") or "",
            "nick": (form.get("irc_nick") or "").strip(),
            "channel": (form.get("irc_channel") or "").strip(),
            "online": irc_block("online"),
            "offline": irc_block("offline"),
        },
    }


def _notify_context(username, stream_title):
    stream_link = f"{SITE_PUBLIC_URL}/live/{username}" if SITE_PUBLIC_URL else f"/live/{username}"
    return {"username": username, "title": stream_title or "", "url": stream_link}


def _render_vars(text, ctx):
    if not text:
        return text
    for key, value in ctx.items():
        text = text.replace("{" + key + "}", value or "")
    return text


def _irc_host_blocked(hostname):
    """Same best-effort SSRF guard as _validate_notify_url, applied to the
    IRC server field (which isn't a URL, so it doesn't go through that
    function)."""
    if not hostname:
        return True
    if hostname == "localhost":
        return True
    if NOTIFY_VALIDATE_URLS:
        try:
            ip = ipaddress.ip_address(hostname)
        except ValueError:
            ip = None
        if ip is not None and any(ip in net for net in _PRIVATE_NETWORKS):
            return True
    return False


def _send_discord(discord_cfg, ctx, state):
    webhook_url = discord_cfg.get("webhook_url")
    if not webhook_url:
        return
    error = _validate_notify_url(webhook_url)
    if error:
        log.warning("skipping discord notify for %s: %s", ctx.get("username"), error)
        return

    block = discord_cfg.get("online" if state == "live" else "offline") or {}
    content = _render_vars(block.get("content", ""), ctx)
    title = _render_vars(block.get("title", ""), ctx)
    description = _render_vars(block.get("description", ""), ctx)

    color_hex = (block.get("color") or "").lstrip("#")
    try:
        color = int(color_hex, 16) if color_hex else None
    except ValueError:
        color = None

    embed = {}
    if title:
        embed["title"] = title
    if description:
        embed["description"] = description
    if color is not None:
        embed["color"] = color

    payload = {}
    if content:
        payload["content"] = content
    if embed:
        payload["embeds"] = [embed]
    if not payload:
        return  # nothing configured for this event, silently do nothing

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url, data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "RakuSpace (https://raku.party, 1.0)",
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=NOTIFY_TIMEOUT_SECONDS)
    except Exception as exc:
        log.warning("discord notification to %s failed: %s", webhook_url, exc)


def _send_irc(irc_cfg, ctx, state):
    server = irc_cfg.get("server")
    channel = irc_cfg.get("channel")
    if not server or not channel:
        return
    if _irc_host_blocked(server):
        log.warning("skipping irc notify: host '%s' is not allowed", server)
        return

    block = irc_cfg.get("online" if state == "live" else "offline") or {}
    body = _render_vars(block.get("body", ""), ctx)
    if not body:
        log.warning("skipping irc notify for %s: no message body configured for '%s' event", channel, state)
        return

    port = irc_cfg.get("port") or (6697 if irc_cfg.get("tls") else 6667)
    nick = irc_cfg.get("nick") or irc_cfg.get("sasl_user") or "rakuspace"
    sasl_user = irc_cfg.get("sasl_user")
    sasl_password = irc_cfg.get("sasl_password")
    server_password = irc_cfg.get("server_password")
    use_sasl = bool(sasl_user and sasl_password)

    # Numeric replies indicating something went wrong with registration/join/send.
    # https://www.alien.net.au/irc/irc2numerics.html
    _ERROR_NUMERICS = {
        "401", "403", "404", "405", "406", "407", "421", "432", "433", "436",
        "437", "442", "451", "461", "464", "465", "471", "473", "474", "475",
        "476", "477", "478", "482", "902", "904", "905", "906", "907",
    }

    log.info("irc notify: connecting to %s:%s (tls=%s, sasl=%s, channel=%s, state=%s)",
              server, port, irc_cfg.get("tls"), use_sasl, channel, state)

    sock = None
    try:
        sock = socket.create_connection((server, port), timeout=NOTIFY_TIMEOUT_SECONDS)
        if irc_cfg.get("tls"):
            ssl_ctx = ssl.create_default_context()
            sock = ssl_ctx.wrap_socket(sock, server_hostname=server)
        sock.settimeout(NOTIFY_TIMEOUT_SECONDS)
        conn = sock.makefile("rwb", buffering=0)
        log.info("irc notify: connected to %s:%s", server, port)

        def send_line(line):
            if line.startswith("PASS ") or line.startswith("AUTHENTICATE "):
                log.debug("irc notify -> %s <redacted>", line.split(" ", 1)[0])
            else:
                log.debug("irc notify -> %s", line)
            conn.write((line + "\r\n").encode("utf-8", errors="replace"))

        def read_until(predicate, max_lines=200):
            # Reads lines (answering PINGs along the way) until predicate(line)
            # is true, the connection ends, or max_lines is hit -- whichever
            # comes first. Best-effort; never blocks past the socket timeout.
            # Logs any numeric error replies seen along the way so failures
            # (bad nick/password/channel/etc) are visible instead of silent.
            for _ in range(max_lines):
                raw_line = conn.readline()
                if not raw_line:
                    log.warning("irc notify: connection to %s closed by server while waiting for a response", server)
                    return None
                text = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                log.debug("irc notify <- %s", text)
                if text.startswith("PING"):
                    send_line("PONG" + text[4:])
                    continue
                parts = text.split()
                if len(parts) > 1 and parts[1] in _ERROR_NUMERICS:
                    log.warning("irc notify: server %s replied with error: %s", server, text)
                if predicate(text):
                    return text
            log.warning("irc notify: gave up waiting for a response from %s after %d lines", server, max_lines)
            return None

        if server_password:
            send_line(f"PASS {server_password}")
        if use_sasl:
            send_line("CAP REQ :sasl")
        send_line(f"NICK {nick}")
        send_line(f"USER {nick} 0 * :{nick}")

        if use_sasl:
            read_until(lambda l: " CAP " in l and "ACK" in l)
            send_line("AUTHENTICATE PLAIN")
            read_until(lambda l: l.startswith("AUTHENTICATE"))
            token = base64.b64encode(f"\0{sasl_user}\0{sasl_password}".encode("utf-8")).decode("ascii")
            send_line(f"AUTHENTICATE {token}")
            sasl_result = read_until(lambda l: " 903 " in l or " 904 " in l or " 905 " in l)
            if sasl_result and " 903 " not in sasl_result:
                log.warning("irc notify: SASL authentication to %s failed: %s", server, sasl_result)
            send_line("CAP END")

        # Wait for registration (numeric 001, RPL_WELCOME) before doing anything else.
        welcome = read_until(lambda l: " 001 " in l)
        if not welcome:
            log.warning("irc notify: never received RPL_WELCOME (001) from %s; proceeding anyway", server)
        else:
            log.info("irc notify: registered with %s as %s", server, nick)

        # Mark ourselves as a bot. Some servers reject this mode change (unknown
        # mode, not permitted, etc) -- that's fine, we still proceed and connect
        # normally either way.
        send_line(f"MODE {nick} +B")

        send_line(f"JOIN {channel}")
        join_result = read_until(lambda l: "JOIN" in l and channel in l)
        if not join_result:
            log.warning("irc notify: no confirmation that %s joined %s; message may not be delivered", nick, channel)
        else:
            log.info("irc notify: joined %s", channel)

        send_line(f"PRIVMSG {channel} :{body}")
        send_line("QUIT :bye")
        log.info("irc notify: sent message to %s on %s", channel, server)
    except Exception:
        log.exception("irc notification to %s failed", server)
    finally:
        try:
            if sock:
                sock.close()
        except Exception:
            pass


def _send_builtin(username, stream_title, notify_config, state):
    cfg = _load_notify_config(notify_config)
    ctx = _notify_context(username, stream_title)
    if cfg.get("discord", {}).get("enabled"):
        _send_discord(cfg["discord"], ctx, state)
    if cfg.get("irc", {}).get("enabled"):
        _send_irc(cfg["irc"], ctx, state)


def _send_notification(notify_url, username, stream_title, state):
    if _validate_notify_url(notify_url):
        # Re-validate defensively in case config tightened after the URL was saved.
        log.warning("skipping notify for %s: URL failed validation", username)
        return

    stream_link = f"{SITE_PUBLIC_URL}/live/{username}" if SITE_PUBLIC_URL else None
    payload = json.dumps({
        "event": state,
        "username": username,
        "stream_title": stream_title,
        "url": stream_link,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }).encode("utf-8")

    req = urllib.request.Request(
        notify_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=NOTIFY_TIMEOUT_SECONDS)
    except Exception as exc:
        log.warning("go-live notification to %s failed: %s", notify_url, exc)


def _notify_reconciler():
    while True:
        time.sleep(NOTIFY_TICK_SECONDS)
        now = time.monotonic()
        due = []
        with _notify_lock:
            for userid, entry in _notify_state.items():
                if entry["state"] == entry["notified_state"]:
                    continue
                if now - entry["changed_at"] < NOTIFY_SETTLE_SECONDS:
                    continue
                due.append((userid, entry["state"]))
                entry["notified_state"] = entry["state"]

        if not due:
            continue

        db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
        try:
            for userid, state in due:
                cur = db.execute(
                    "SELECT username, stream_title, notify_url, notify_builtin, notify_config, "
                    "notify_on_live, notify_on_offline FROM users WHERE userid=?",
                    (userid,),
                )
                row = cur.fetchone()
                if not row:
                    continue

                wants_event = row["notify_on_live"] if state == "live" else row["notify_on_offline"]
                if not wants_event:
                    continue

                if row["notify_builtin"]:
                    _send_builtin(row["username"], row["stream_title"], row["notify_config"], state)
                elif row["notify_url"]:
                    _send_notification(row["notify_url"], row["username"], row["stream_title"], state)
        finally:
            db.close()


threading.Thread(target=_notify_reconciler, daemon=True).start()


# --- Routes ---
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/multistream")
def multistream():
    return render_template("multistream.html")

@app.route("/api/check/<streamname>")
def check_stream(streamname):
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT 1 FROM users WHERE username=?", (streamname,))
    exists = cur.fetchone() is not None
    return jsonify({"known": exists})



@app.route("/live/<streamname>")
def play_stream(streamname):
    db = get_db()
    with db:
        cur = db.cursor()
        cur.execute("SELECT stream_title FROM users WHERE username=?", (streamname,))
        row = cur.fetchone()
        streamtitle = row["stream_title"] if row else None

        return render_template(
            "player.html",
            streamname=streamname,
            streamtitle=streamtitle,
            OME_PUBLISHER_HOST=OME_PUBLISHER_HOST,
            OME_PUBLISHER_PORT=OME_PUBLISHER_PORT,
            OME_APP_NAME=OME_APP_NAME
        )


@app.route("/stream_info")
@require_auth
def stream_page(username):
    # In production this comes from Authelia/NGINX via REMOTE_USER header

    userid, streamkey = get_or_create_userkey(username)

    db = get_db()
    cur = db.cursor()
    cur.execute(
        "SELECT stream_title, notify_url, notify_builtin, notify_on_live, notify_on_offline "
        "FROM users WHERE username=?",
        (username,),
    )
    row = cur.fetchone()
    streamtitle = row["stream_title"] if row else None
    notify_url = row["notify_url"] if row else None
    notify_builtin = bool(row["notify_builtin"]) if row else False
    notify_on_live = bool(row["notify_on_live"]) if row else True
    notify_on_offline = bool(row["notify_on_offline"]) if row else False

    return render_template(
        "stream.html",
        username=username,
        userid=userid,
        streamkey=streamkey,
        streamtitle=streamtitle,
        rtmp_urls=RTMP_URLS,
        notify_url=notify_url,
        notify_builtin=notify_builtin,
        notify_on_live=notify_on_live,
        notify_on_offline=notify_on_offline,
        notify_error=None,
    )


@app.route("/stream_info/regen_key", methods=["POST"])
@require_auth
def regen_key(username):
    get_or_create_userkey(username, regen=True)
    return redirect(url_for("stream_page"))


@app.route("/stream_info/save_settings", methods=["POST"])
@require_auth
def save_settings(username):
    streamtitle = request.form.get("streamtitle")
    notify_url = (request.form.get("notify_url") or "").strip()
    notify_builtin = request.form.get("notify_builtin") == "on"
    notify_on_live = request.form.get("notify_on_live") == "on"
    notify_on_offline = request.form.get("notify_on_offline") == "on"

    error = None
    if not notify_builtin:
        error = _validate_notify_url(notify_url)

    if error:
        userid, streamkey = get_or_create_userkey(username)
        return render_template(
            "stream.html",
            username=username,
            userid=userid,
            streamkey=streamkey,
            streamtitle=streamtitle,
            rtmp_urls=RTMP_URLS,
            notify_url=notify_url,
            notify_builtin=notify_builtin,
            notify_on_live=notify_on_live,
            notify_on_offline=notify_on_offline,
            notify_error=error,
        ), 400

    db = get_db()
    with db:
        db.execute(
            "UPDATE users SET stream_title=?, notify_url=?, notify_builtin=?, notify_on_live=?, notify_on_offline=? "
            "WHERE username=?",
            (streamtitle, notify_url or None, int(notify_builtin), int(notify_on_live), int(notify_on_offline), username),
        )

    return redirect(url_for("stream_page"))


@app.route("/stream_info/notifications")
@require_auth
def notifications_page(username):
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT notify_config FROM users WHERE username=?", (username,))
    row = cur.fetchone()
    cfg = _load_notify_config(row["notify_config"] if row else None)

    return render_template(
        "notifications.html",
        username=username,
        cfg=cfg,
        notify_error=None,
        test_status=None,
    )


@app.route("/stream_info/notifications", methods=["POST"])
@require_auth
def set_notifications(username):
    cfg = _parse_notify_config(request.form)

    error = None
    if cfg["discord"]["enabled"]:
        error = _validate_notify_url(cfg["discord"]["webhook_url"])
        if not cfg["discord"]["webhook_url"]:
            error = "Discord webhook URL is required when Discord is enabled."
    if not error and cfg["irc"]["enabled"]:
        if not cfg["irc"]["server"] or not cfg["irc"]["channel"]:
            error = "IRC server and channel are required when IRC is enabled."
        elif _irc_host_blocked(cfg["irc"]["server"]):
            error = "IRC server may not target localhost or a private/loopback address."

    if error:
        return render_template(
            "notifications.html",
            username=username,
            cfg=cfg,
            notify_error=error,
            test_status=None,
        ), 400

    db = get_db()
    with db:
        db.execute(
            "UPDATE users SET notify_config=? WHERE username=?",
            (json.dumps(cfg), username),
        )

    return redirect(url_for("notifications_page"))


@app.route("/stream_info/notifications/test", methods=["POST"])
@require_auth
def test_notification(username):
    cfg = _parse_notify_config(request.form)
    channel = request.form.get("channel")

    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT stream_title FROM users WHERE username=?", (username,))
    row = cur.fetchone()
    streamtitle = row["stream_title"] if row else None
    ctx = _notify_context(username, streamtitle)

    status = None
    try:
        if channel == "discord":
            if not cfg["discord"]["webhook_url"]:
                status = "Enter a Discord webhook URL before sending a test."
            else:
                _send_discord(cfg["discord"], ctx, "live")
                status = "Discord test notification sent (check the channel)."
        elif channel == "irc":
            if not cfg["irc"]["server"] or not cfg["irc"]["channel"]:
                status = "Enter an IRC server and channel before sending a test."
            elif not cfg["irc"]["online"]["body"]:
                status = "Enter an online message before sending a test (the test uses the 'online' template)."
            else:
                _send_irc(cfg["irc"], ctx, "live")
                status = "IRC test notification sent (check the channel)."
        else:
            status = "Unknown notification channel."
    except Exception as exc:
        log.warning("test notification failed: %s", exc)
        status = "Test notification failed, check server logs."

    return render_template(
        "notifications.html",
        username=username,
        cfg=cfg,
        notify_error=None,
        test_status=status,
    )


@app.route("/auth/ome", methods=["POST"])
def verify_webhook():
    deny = jsonify({"allowed": False})
    data = request.json or {} # Fallback to empty dict if no json
    req = data.get("request", {})

    url = req.get("url", "")
    # 1. Strip rogue single and double quotes so urlparse can read the scheme
    url = url.strip("'\"")

    direction = req.get("direction")
    status = req.get("status")

    parsed_uri = urlparse(url)
    #print(f"DEBUG Parsed URI: {parsed_uri}")

    # 2. Safely extract hostname, defaulting to empty string if None
    hostname = parsed_uri.hostname or ""

    if hostname != OME_PROVIDER_HOST and hostname not in RTMP_ALT_HOSTS:
        return deny

    # We only care about publish/open
    if direction == "incoming" and status == "opening":
        try: 
            # 4. Safely extract the stream key from paths like /live/1_key
            # Split by '/' first to drop the app name ('live'), then grab the last piece
            key_part = parsed_uri.path.strip('/').split('/')[-1] 

            userid_str, key = key_part.split("_", 1)
            userid = int(userid_str)
        except (ValueError, AttributeError, IndexError):
            return deny

        # Lookup user from key
        db = get_db()
        with db:  
            cur = db.cursor()
            cur.execute("SELECT username, streamkey FROM users WHERE userid=?", (userid,))
            row = cur.fetchone()

        if not row:
            return deny

        username, correct_key = row
        if secrets.compare_digest(correct_key, key):
            _set_notify_state(userid, "live")
            new_url = f"{RTMP_HOST}/{username}"
            return jsonify({
                "allowed": True,
                "new_url": new_url,
                "lifetime": 0,
                "reason": "authorized"
            })
        else:
            return deny

    if status == "closing":
        # Best-effort: record the stream as offline for notification purposes.
        # Any malformed path is silently ignored -- this is not an auth decision.
        try:
            key_part = parsed_uri.path.strip('/').split('/')[-1]
            userid_str, _key = key_part.split("_", 1)
            _set_notify_state(int(userid_str), "offline")
        except (ValueError, AttributeError, IndexError):
            pass
        return jsonify({}) # Flask prefers returning actual Response objects or dicts

    return deny # Catch-all denial for unhandled statuses

# --- Debug Server ---
SITE_HOST = app.config['SITE_HOST']
SITE_PORT = app.config['SITE_PORT']
if __name__ == '__main__':
    socketio.run(app, host=SITE_HOST, port=int(SITE_PORT),
                 debug=True, use_reloader=True)

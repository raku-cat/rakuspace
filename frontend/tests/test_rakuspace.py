import json
import re
import sqlite3
import string

import RakuSpace as rakuspace


# --- generate_stream_key ---

def test_generate_stream_key_length_and_alphabet():
    key = rakuspace.generate_stream_key()
    assert len(key) == 30
    assert all(c in string.ascii_letters + string.digits for c in key)


def test_generate_stream_key_is_random():
    keys = {rakuspace.generate_stream_key() for _ in range(20)}
    assert len(keys) == 20  # extremely unlikely to collide


# --- get_or_create_userkey ---

def test_get_or_create_userkey_creates_then_reuses(client, db_path):
    with rakuspace.app.test_request_context():
        userid1, key1, row1 = rakuspace.get_or_create_userkey("alice")
        assert row1 is None  # brand new user, no existing row
        userid2, key2, row2 = rakuspace.get_or_create_userkey("alice")
        assert (userid1, key1) == (userid2, key2)
        assert row2 is not None and row2["stream_title"] is None


def test_get_or_create_userkey_regen_changes_key(client, db_path):
    with rakuspace.app.test_request_context():
        userid1, key1, _ = rakuspace.get_or_create_userkey("bob")
        userid2, key2, row2 = rakuspace.get_or_create_userkey("bob", regen=True)
        assert userid1 == userid2
        assert key1 != key2
        assert row2["userid"] == userid1


# --- _validate_notify_url ---

def test_validate_notify_url_empty_is_ok():
    assert rakuspace._validate_notify_url("") is None


def test_validate_notify_url_rejects_bad_scheme():
    assert rakuspace._validate_notify_url("ftp://example.com") is not None


def test_validate_notify_url_rejects_localhost():
    assert rakuspace._validate_notify_url("http://localhost/hook") is not None


def test_validate_notify_url_rejects_private_ip():
    assert rakuspace._validate_notify_url("http://127.0.0.1/hook") is not None
    assert rakuspace._validate_notify_url("http://10.1.2.3/hook") is not None


def test_validate_notify_url_accepts_public_host():
    assert rakuspace._validate_notify_url("https://discord.com/api/webhooks/x") is None


# --- irc_embed_url ---

def test_irc_embed_url_disabled_without_config(monkeypatch):
    monkeypatch.setattr(rakuspace, "IRC_EMBED_BASE_URL", "")
    assert rakuspace.irc_embed_url("#general") is None


def test_irc_embed_url_builds_token(monkeypatch):
    monkeypatch.setattr(rakuspace, "IRC_EMBED_BASE_URL", "https://chat.example.com")
    monkeypatch.setattr(rakuspace, "IRC_EMBED_SECRET", "shared-secret")
    url = rakuspace.irc_embed_url("general")
    assert url is not None
    assert url.startswith("https://chat.example.com/?channel=%23general&token=")


def test_irc_embed_url_deterministic(monkeypatch):
    monkeypatch.setattr(rakuspace, "IRC_EMBED_BASE_URL", "https://chat.example.com")
    monkeypatch.setattr(rakuspace, "IRC_EMBED_SECRET", "shared-secret")
    assert rakuspace.irc_embed_url("#general") == rakuspace.irc_embed_url("#general")
    assert rakuspace.irc_embed_url("#General") == rakuspace.irc_embed_url("#general")


def test_irc_embed_url_rejects_invalid_channel(monkeypatch):
    monkeypatch.setattr(rakuspace, "IRC_EMBED_BASE_URL", "https://chat.example.com")
    monkeypatch.setattr(rakuspace, "IRC_EMBED_SECRET", "shared-secret")
    assert rakuspace.irc_embed_url("has space") is None
    assert rakuspace.irc_embed_url("") is None


# --- _render_vars / notify config ---

def test_render_vars_substitutes_known_keys():
    ctx = {"username": "alice", "title": "Cool stream", "url": "http://x/live/alice"}
    out = rakuspace._render_vars("{username} is live: {title} ({url})", ctx)
    assert out == "alice is live: Cool stream (http://x/live/alice)"


def test_render_vars_handles_none_and_empty():
    assert rakuspace._render_vars("", {"a": "b"}) == ""
    assert rakuspace._render_vars(None, {"a": "b"}) is None


def test_load_notify_config_defaults_on_empty():
    cfg = rakuspace._load_notify_config(None)
    assert cfg["discord"]["enabled"] is False
    assert cfg["irc"]["enabled"] is False


def test_load_notify_config_merges_over_defaults():
    raw = json.dumps({"discord": {"enabled": True, "webhook_url": "https://discord.com/x"}})
    cfg = rakuspace._load_notify_config(raw)
    assert cfg["discord"]["enabled"] is True
    assert cfg["discord"]["webhook_url"] == "https://discord.com/x"
    # Untouched defaults still present.
    assert cfg["discord"]["online"]["title"] == "{username} is live!"
    assert cfg["irc"]["enabled"] is False


def test_load_notify_config_ignores_garbage_json():
    cfg = rakuspace._load_notify_config("not json")
    assert cfg == rakuspace._default_notify_config()


# --- require_auth ---

def test_require_auth_rejects_without_headers(client):
    resp = client.get("/stream_info")
    assert resp.status_code == 401


def test_require_auth_accepts_forwarded_user_header(client):
    resp = client.get("/stream_info", headers={"X-Forwarded-User": "alice"})
    assert resp.status_code == 200


def test_require_auth_basicauth_disabled_ignores_basic_header(client, monkeypatch):
    monkeypatch.setitem(rakuspace.app.config, "BASICAUTH_ENABLED", "False")
    resp = client.get("/stream_info", headers={"Authorization": "Basic YWxpY2U6cGFzcw=="})  # alice:pass
    assert resp.status_code == 401


def test_require_auth_basicauth_enabled_reads_username(client, monkeypatch):
    monkeypatch.setitem(rakuspace.app.config, "BASICAUTH_ENABLED", "True")
    resp = client.get("/stream_info", headers={"Authorization": "Basic YWxpY2U6cGFzcw=="})  # alice:pass
    assert resp.status_code == 200


# --- basic routes ---

def test_index_route(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_api_check_unknown_stream(client):
    resp = client.get("/api/check/nobody")
    assert resp.status_code == 200
    assert resp.get_json() == {"known": False}


def test_api_check_known_stream(client, db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO users (username, streamkey) VALUES ('alice', 'k')")
    conn.commit()
    conn.close()

    resp = client.get("/api/check/alice")
    assert resp.get_json() == {"known": True}


def test_play_stream_unknown_streamer_still_renders(client):
    resp = client.get("/live/nobody")
    assert resp.status_code == 200


# --- CSRF protection ---

def test_regen_key_requires_csrf_token(client):
    client.get("/stream_info", headers={"X-Forwarded-User": "alice"})  # creates the user
    rakuspace.app.config["WTF_CSRF_ENABLED"] = True
    try:
        resp = client.post(
            "/stream_info/regen_key",
            headers={"X-Forwarded-User": "alice"},
        )
        assert resp.status_code == 400
    finally:
        rakuspace.app.config["WTF_CSRF_ENABLED"] = False


def test_regen_key_succeeds_with_csrf_token(client):
    rakuspace.app.config["WTF_CSRF_ENABLED"] = True
    try:
        # Same flow a real browser follows: load the page carrying the
        # session cookie + embedded token, then submit it back.
        page = client.get("/stream_info", headers={"X-Forwarded-User": "alice"}).get_data(as_text=True)
        match = re.search(r'name="csrf_token" value="([^"]+)"', page)
        assert match, "expected a csrf_token hidden field on the stream_info page"
        resp = client.post(
            "/stream_info/regen_key",
            data={"csrf_token": match.group(1)},
            headers={"X-Forwarded-User": "alice"},
        )
        assert resp.status_code in (302, 303)
    finally:
        rakuspace.app.config["WTF_CSRF_ENABLED"] = False


def test_ome_webhook_exempt_from_csrf(client, db_path):
    _insert_user(db_path, "alice", "correct-key", userid=1)
    rakuspace.app.config["WTF_CSRF_ENABLED"] = True
    try:
        url = f"rtmp://{rakuspace.OME_PROVIDER_HOST}/{rakuspace.OME_APP_NAME}/1_correct-key"
        resp = client.post(
            "/auth/ome",
            json={"request": {"direction": "incoming", "status": "opening", "url": url}},
        )
        assert resp.status_code == 200
        assert resp.get_json()["allowed"] is True
    finally:
        rakuspace.app.config["WTF_CSRF_ENABLED"] = False


# --- /auth/ome webhook ---

def _insert_user(db_path, username, streamkey, userid=1):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO users (userid, username, streamkey) VALUES (?, ?, ?)",
        (userid, username, streamkey),
    )
    conn.commit()
    conn.close()


def test_webhook_denies_unknown_host(client):
    resp = client.post(
        "/auth/ome",
        json={"request": {"direction": "incoming", "status": "opening", "url": "rtmp://evil.example.com/app/1_key"}},
    )
    assert resp.get_json() == {"allowed": False}


def test_webhook_allows_correct_key(client, db_path):
    _insert_user(db_path, "alice", "correct-key", userid=1)
    url = f"rtmp://{rakuspace.OME_PROVIDER_HOST}/{rakuspace.OME_APP_NAME}/1_correct-key"
    resp = client.post(
        "/auth/ome",
        json={"request": {"direction": "incoming", "status": "opening", "url": url}},
    )
    data = resp.get_json()
    assert data["allowed"] is True
    assert data["new_url"] == f"{rakuspace.RTMP_HOST}/alice"


def test_webhook_denies_wrong_key(client, db_path):
    _insert_user(db_path, "alice", "correct-key", userid=1)
    url = f"rtmp://{rakuspace.OME_PROVIDER_HOST}/{rakuspace.OME_APP_NAME}/1_wrong-key"
    resp = client.post(
        "/auth/ome",
        json={"request": {"direction": "incoming", "status": "opening", "url": url}},
    )
    assert resp.get_json() == {"allowed": False}


def test_webhook_denies_unknown_userid(client, db_path):
    url = f"rtmp://{rakuspace.OME_PROVIDER_HOST}/{rakuspace.OME_APP_NAME}/999_whatever"
    resp = client.post(
        "/auth/ome",
        json={"request": {"direction": "incoming", "status": "opening", "url": url}},
    )
    assert resp.get_json() == {"allowed": False}


def test_webhook_closing_is_best_effort_and_never_errors(client, db_path):
    _insert_user(db_path, "alice", "correct-key", userid=1)
    url = f"rtmp://{rakuspace.OME_PROVIDER_HOST}/{rakuspace.OME_APP_NAME}/1_correct-key"
    resp = client.post(
        "/auth/ome",
        json={"request": {"direction": "incoming", "status": "closing", "url": url}},
    )
    assert resp.status_code == 200

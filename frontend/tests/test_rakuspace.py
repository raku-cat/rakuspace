import json
import re
import sqlite3
import string

import pytest

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
    assert resp.get_json() == {"known": False, "title": None, "name": None}


def test_api_check_known_stream(client, db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO users (username, streamkey) VALUES ('alice', 'k')")
    conn.commit()
    conn.close()

    resp = client.get("/api/check/alice")
    assert resp.get_json() == {"known": True, "title": None, "name": "alice"}


def test_api_check_returns_stream_title(client, db_path):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO users (username, streamkey, stream_title) VALUES ('bob', 'k', 'Perfect Dark 100%')"
    )
    conn.commit()
    conn.close()

    resp = client.get("/api/check/bob")
    assert resp.get_json() == {"known": True, "title": "Perfect Dark 100%", "name": "bob"}


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


# --- viewer tracking ---

@pytest.fixture(autouse=True)
def _clear_viewers():
    # These tests write directly into rakuspace._viewers, which is
    # process-global state shared across the whole test session.
    rakuspace._viewers.clear()
    yield
    rakuspace._viewers.clear()


def test_viewer_snapshot_empty_stream():
    assert rakuspace._viewer_snapshot("nobody-watching") == (0, [])


def test_viewer_snapshot_counts_anonymous_connections_individually():
    rakuspace._register_viewer("stream", "conn-a", None)
    rakuspace._register_viewer("stream", "conn-b", None)
    count, named = rakuspace._viewer_snapshot("stream")
    assert count == 2
    assert named == []


def test_viewer_snapshot_dedups_same_username_across_connections():
    rakuspace._register_viewer("stream", "conn-a", "alice")
    rakuspace._register_viewer("stream", "conn-b", "alice")  # e.g. two tabs
    count, named = rakuspace._viewer_snapshot("stream")
    assert count == 1
    assert named == ["alice"]


def test_viewer_snapshot_mixes_named_and_anonymous():
    rakuspace._register_viewer("stream", "conn-a", "alice")
    rakuspace._register_viewer("stream", "conn-b", "bob")
    rakuspace._register_viewer("stream", "conn-c", None)
    count, named = rakuspace._viewer_snapshot("stream")
    assert count == 3
    assert named == ["alice", "bob"]


def test_viewer_snapshot_is_scoped_per_stream():
    rakuspace._register_viewer("stream-a", "conn-1", "alice")
    rakuspace._register_viewer("stream-b", "conn-2", "bob")
    assert rakuspace._viewer_snapshot("stream-a") == (1, ["alice"])
    assert rakuspace._viewer_snapshot("stream-b") == (1, ["bob"])


def test_unregister_viewer_removes_entry():
    rakuspace._register_viewer("stream", "conn-a", "alice")
    rakuspace._unregister_viewer("stream", "conn-a")
    assert rakuspace._viewer_snapshot("stream") == (0, [])
    assert "stream" not in rakuspace._viewers


def test_unregister_unknown_conn_is_a_noop():
    rakuspace._register_viewer("stream", "conn-a", "alice")
    rakuspace._unregister_viewer("stream", "does-not-exist")
    assert rakuspace._viewer_snapshot("stream") == (1, ["alice"])


def test_viewer_snapshot_expires_stale_entries(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(rakuspace.time, "monotonic", lambda: clock[0])

    rakuspace._register_viewer("stream", "conn-a", "alice")
    assert rakuspace._viewer_snapshot("stream") == (1, ["alice"])

    clock[0] += rakuspace.VIEWER_TTL_SECONDS + 1
    assert rakuspace._viewer_snapshot("stream") == (0, [])
    # The stale connection was pruned, not just hidden from the count.
    assert "stream" not in rakuspace._viewers


def test_touch_viewer_resets_the_ttl_clock(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(rakuspace.time, "monotonic", lambda: clock[0])

    rakuspace._register_viewer("stream", "conn-a", "alice")
    clock[0] += rakuspace.VIEWER_TTL_SECONDS - 1
    rakuspace._touch_viewer("stream", "conn-a")

    clock[0] += rakuspace.VIEWER_TTL_SECONDS - 1
    assert rakuspace._viewer_snapshot("stream") == (1, ["alice"])


def test_viewers_event_omits_named_list_for_anonymous_viewer():
    event = rakuspace._viewers_event(3, ["alice", "bob"], viewer_username=None)
    assert event.startswith("event: viewers\ndata: ")
    payload = json.loads(event.split("data: ", 1)[1].strip())
    assert payload == {"count": 3}


def test_viewers_event_includes_named_list_for_logged_in_viewer():
    event = rakuspace._viewers_event(3, ["alice", "bob"], viewer_username="alice")
    payload = json.loads(event.split("data: ", 1)[1].strip())
    assert payload == {"count": 3, "viewers": ["alice", "bob"]}


def test_resolve_username_returns_none_without_headers(client):
    with rakuspace.app.test_request_context("/"):
        assert rakuspace._resolve_username() is None


def test_resolve_username_reads_forwarded_user_header(client):
    with rakuspace.app.test_request_context("/", headers={"X-Forwarded-User": "alice"}):
        assert rakuspace._resolve_username() == "alice"


def test_live_events_registers_and_unregisters_viewer(client):
    # The route's generator loops forever (it's a long-lived SSE stream), so
    # it's driven directly here rather than through the test client (which
    # would hang trying to read a complete response body). Pulling the first
    # two yields mirrors a client that just connected; closing the generator
    # mirrors that client disconnecting, which is what should trigger the
    # finally block that unregisters the viewer.
    with rakuspace.app.test_request_context(
        "/api/live/some-streamer/events", headers={"X-Forwarded-User": "alice"}
    ):
        resp = rakuspace.live_events("some-streamer")
        gen = resp.response
        state_event = next(gen)
        viewers_event = next(gen)
        assert state_event == "event: state\ndata: offline\n\n"
        assert '"count": 1' in viewers_event
        assert '"viewers": ["alice"]' in viewers_event
        assert rakuspace._viewer_snapshot("some-streamer") == (1, ["alice"])
        gen.close()

    assert "some-streamer" not in rakuspace._viewers


# --- case-insensitive usernames ---

def _add_user(db_path, username, streamkey="k", title=None):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO users (username, streamkey, stream_title) VALUES (?, ?, ?)",
        (username, streamkey, title),
    )
    conn.commit()
    conn.close()


@pytest.mark.parametrize("typed", ["Raku", "RAku", "rakU", "RAKU"])
def test_play_stream_redirects_other_case_to_stored_name(client, db_path, typed):
    _add_user(db_path, "raku")
    resp = client.get(f"/live/{typed}")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/live/raku")


def test_play_stream_exact_case_renders(client, db_path):
    _add_user(db_path, "raku", title="hi")
    resp = client.get("/live/raku")
    assert resp.status_code == 200
    assert b"hi" in resp.data


def test_play_stream_redirect_keeps_query_string(client, db_path):
    _add_user(db_path, "raku")
    resp = client.get("/live/Raku?muted=1")
    assert resp.headers["Location"].endswith("/live/raku?muted=1")


def test_play_stream_lite_redirects_other_case(client, db_path):
    _add_user(db_path, "raku")
    resp = client.get("/lite/live/RAKU")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/lite/live/raku")


def test_api_check_is_case_insensitive(client, db_path):
    _add_user(db_path, "raku", title="hi")
    resp = client.get("/api/check/RaKu")
    assert resp.get_json() == {"known": True, "title": "hi", "name": "raku"}


def test_canonical_username_prefers_exact_match(client, db_path):
    # Older DBs may already hold two rows differing only by case.
    _add_user(db_path, "raku")
    _add_user(db_path, "Raku")
    with rakuspace.app.app_context():
        assert rakuspace._canonical_username("Raku") == "Raku"
        assert rakuspace._canonical_username("raku") == "raku"
        assert rakuspace._canonical_username("RAKU") in ("raku", "Raku")
        assert rakuspace._canonical_username("nobody") is None


def test_auth_header_other_case_reuses_existing_user(client, db_path):
    _add_user(db_path, "raku", streamkey="thekey")
    resp = client.get("/stream_info", headers={"X-Forwarded-User": "Raku"})
    assert resp.status_code == 200
    assert b"thekey" in resp.data
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    conn.close()
    assert count == 1


def test_live_events_other_case_shares_state_with_stored_name(client, db_path):
    _add_user(db_path, "raku")
    rakuspace._set_live_state("raku", "live")
    try:
        with rakuspace.app.test_request_context("/api/live/RAKU/events"):
            gen = rakuspace.live_events("RAKU").response
            assert next(gen) == "event: state\ndata: live\n\n"
            next(gen)
            assert rakuspace._viewer_snapshot("raku")[0] == 1
            gen.close()
    finally:
        rakuspace._set_live_state("raku", "offline")

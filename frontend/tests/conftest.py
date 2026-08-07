import os
import sqlite3
import sys

import pytest

FRONTEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, FRONTEND_DIR)

if not os.path.exists(os.path.join(FRONTEND_DIR, "rakuspace.cfg")):
    pytest.skip(
        "rakuspace.cfg not found -- run `cp rakuspace.cfg.example rakuspace.cfg` "
        "in frontend/ per the README before running tests",
        allow_module_level=True,
    )

import RakuSpace as rakuspace  # noqa: E402


def _init_schema(db_path):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                userid INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                streamkey TEXT NOT NULL,
                stream_title TEXT,
                notify_url TEXT,
                notify_builtin INTEGER NOT NULL DEFAULT 0,
                notify_on_live INTEGER NOT NULL DEFAULT 1,
                notify_on_offline INTEGER NOT NULL DEFAULT 0,
                notify_config TEXT,
                offline_image_url TEXT,
                chat_channel TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    """Points the app at a throwaway sqlite DB for the duration of a test, so
    tests never read or write the real users.db."""
    path = str(tmp_path / "test_users.db")
    _init_schema(path)
    monkeypatch.setattr(rakuspace, "DB_PATH", path)
    return path


@pytest.fixture
def client(db_path):
    rakuspace.app.config["TESTING"] = True
    # Route-level logic is what's under test here, not CSRF enforcement
    # itself -- exercising the real token flow would need a real session
    # per request, which just adds noise to these tests.
    rakuspace.app.config["WTF_CSRF_ENABLED"] = False
    with rakuspace.app.test_client() as c:
        yield c


@pytest.fixture
def app():
    return rakuspace.app

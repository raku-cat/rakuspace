import sqlite3
import os
import types

config = types.ModuleType("config")
with open("rakuspace.cfg", "r") as f:
    exec(f.read(), config.__dict__)

DB_PATH = config.DB_PATH

def init_db():
    # Remove existing DB if it exists
    if not os.path.exists(DB_PATH):

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Create the users table
        c.execute("""
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
        """)

        conn.commit()
        conn.close()
        print(f"Database initialized at {DB_PATH}")
    else:
        print(f"Database {DB_PATH} already exists, remove or replace it. Exiting.")

if __name__ == "__main__":
    init_db()

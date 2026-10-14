import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

DB_DIR = Path("data")
DB_PATH = DB_DIR / "big_brain.db"
_DATABASE_LOCK = asyncio.Lock()


@asynccontextmanager
async def connect_db(path=DB_PATH):
    """Serialize this process's SQLite access and wait through short locks."""
    async with _DATABASE_LOCK:
        async with aiosqlite.connect(path, timeout=30.0) as db:
            await db.execute("PRAGMA busy_timeout=30000")
            yield db


async def init_database():
    DB_DIR.mkdir(parents=True, exist_ok=True)

    async with connect_db(DB_PATH) as db:

        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA foreign_keys=ON;")

        # Every message seen by Big Brain
        await db.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            message_id INTEGER PRIMARY KEY,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            author_id INTEGER NOT NULL,

            author_name TEXT,
            author_display_name TEXT,

            content TEXT,

            created_at TEXT NOT NULL,
            edited_at TEXT,

            reply_to_message_id INTEGER,

            is_bot INTEGER DEFAULT 0,
            is_webhook INTEGER DEFAULT 0,
            is_pinned INTEGER DEFAULT 0,

            deleted INTEGER DEFAULT 0,
            deleted_at TEXT
        )
        """)

        # Complete edit history
        await db.execute("""
        CREATE TABLE IF NOT EXISTS message_edits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            message_id INTEGER NOT NULL,

            old_content TEXT,
            new_content TEXT,

            edited_at TEXT NOT NULL
        )
        """)

        # Attachments
        await db.execute("""
        CREATE TABLE IF NOT EXISTS attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            attachment_id INTEGER UNIQUE,

            message_id INTEGER NOT NULL,

            filename TEXT,
            content_type TEXT,

            size INTEGER,

            original_url TEXT,
            proxy_url TEXT,

            local_path TEXT,

            width INTEGER,
            height INTEGER,

            saved_at TEXT
        )
        """)

        # Reactions
        await db.execute("""
        CREATE TABLE IF NOT EXISTS reactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            message_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            user_id INTEGER,

            emoji TEXT,

            action TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
        """)

        # Member events/history
        await db.execute("""
        CREATE TABLE IF NOT EXISTS member_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,

            event_type TEXT NOT NULL,

            old_value TEXT,
            new_value TEXT,

            timestamp TEXT NOT NULL
        )
        """)

        # Presence/activity history
        await db.execute("""
        CREATE TABLE IF NOT EXISTS presence_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,

            old_status TEXT,
            new_status TEXT,

            old_activity TEXT,
            new_activity TEXT,

            timestamp TEXT NOT NULL
        )
        """)

        # Voice history
        await db.execute("""
        CREATE TABLE IF NOT EXISTS voice_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,

            event_type TEXT NOT NULL,

            old_channel_id INTEGER,
            new_channel_id INTEGER,

            self_mute INTEGER,
            self_deaf INTEGER,
            server_mute INTEGER,
            server_deaf INTEGER,

            self_stream INTEGER,
            self_video INTEGER,

            timestamp TEXT NOT NULL
        )
        """)

        # Generic server events
        await db.execute("""
        CREATE TABLE IF NOT EXISTS server_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            guild_id INTEGER NOT NULL,

            event_type TEXT NOT NULL,

            target_id INTEGER,
            actor_id INTEGER,

            data TEXT,

            timestamp TEXT NOT NULL
        )
        """)

        # Audit-log archive
        await db.execute("""
        CREATE TABLE IF NOT EXISTS audit_events (
            audit_id INTEGER PRIMARY KEY,

            guild_id INTEGER NOT NULL,

            action TEXT,

            actor_id INTEGER,
            target_id INTEGER,

            reason TEXT,
            changes TEXT,
            extra TEXT,

            created_at TEXT NOT NULL
        )
        """)

        # Useful indexes
        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_author
        ON messages(author_id)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_channel
        ON messages(channel_id)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_created
        ON messages(created_at)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_edits_message
        ON message_edits(message_id)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_member_events_user
        ON member_events(user_id)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_presence_user
        ON presence_events(user_id)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_voice_user
        ON voice_events(user_id)
        """)

        await db.commit()

    print(f"Database ready: {DB_PATH}")

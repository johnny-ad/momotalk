"""
Cross-bot communication system.
Handles quiet hours, shared state, and bot coordination.
"""
import aiosqlite
import json
from datetime import datetime, timedelta
from database import DB_PATH


async def init_crossbot_table():
    """Create cross-bot communication table."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bot_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                set_by TEXT NOT NULL,
                expires_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()


async def set_quiet_hours(duration_minutes: int = 60, set_by: str = "hina"):
    """
    Enable quiet hours. All bots should check this before sending unprompted messages.
    """
    await init_crossbot_table()
    expires = datetime.now() + timedelta(minutes=duration_minutes)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO bot_state (key, value, set_by, expires_at) VALUES (?, ?, ?, ?)",
            ("quiet_hours", json.dumps({"active": True, "duration": duration_minutes}), set_by, expires.isoformat()),
        )
        await db.commit()


async def is_quiet_hours() -> bool:
    """Check if quiet hours are currently active."""
    await init_crossbot_table()

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT value, expires_at FROM bot_state WHERE key = 'quiet_hours'"
        )
        row = await cursor.fetchone()

        if not row:
            return False

        expires = datetime.fromisoformat(row["expires_at"])
        if datetime.now() > expires:
            # Expired — clean up
            await db.execute("DELETE FROM bot_state WHERE key = 'quiet_hours'")
            await db.commit()
            return False

        data = json.loads(row["value"])
        return data.get("active", False)


async def end_quiet_hours():
    """Manually end quiet hours."""
    await init_crossbot_table()

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM bot_state WHERE key = 'quiet_hours'")
        await db.commit()


async def set_shared_state(key: str, value: str, set_by: str, ttl_minutes: int = None):
    """Set a shared state value that other bots can read."""
    await init_crossbot_table()

    expires = None
    if ttl_minutes:
        expires = (datetime.now() + timedelta(minutes=ttl_minutes)).isoformat()

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO bot_state (key, value, set_by, expires_at) VALUES (?, ?, ?, ?)",
            (key, value, set_by, expires),
        )
        await db.commit()


async def get_shared_state(key: str) -> str | None:
    """Get a shared state value."""
    await init_crossbot_table()

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT value, expires_at FROM bot_state WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()

        if not row:
            return None

        # Check expiry
        if row["expires_at"]:
            expires = datetime.fromisoformat(row["expires_at"])
            if datetime.now() > expires:
                await db.execute("DELETE FROM bot_state WHERE key = ?", (key,))
                await db.commit()
                return None

        return row["value"]

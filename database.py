import aiosqlite
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "momotalk.db")


async def init_db():
    """Create tables if they don't exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS bot_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                set_by TEXT NOT NULL,
                expires_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Pending user messages — queued when bot is delayed or asleep
        await db.execute("""
            CREATE TABLE IF NOT EXISTS pending_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.commit()


async def save_message(character: str, role: str, content: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO messages (character, role, content) VALUES (?, ?, ?)",
            (character, role, content),
        )
        await db.commit()


async def get_message_history(character: str, limit: int = 50) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT role, content, timestamp FROM messages WHERE character = ? ORDER BY timestamp DESC LIMIT ?",
            (character, limit),
        )
        rows = await cursor.fetchall()
        return [{"role": row["role"], "content": row["content"], "timestamp": row["timestamp"]} for row in reversed(rows)]


async def add_pending_user_message(character: str, content: str):
    """Queue a user message for when the bot responds later."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO pending_messages (character, content) VALUES (?, ?)",
            (character, content),
        )
        await db.commit()


async def get_pending_user_messages(character: str) -> list[str]:
    """Get all pending user messages for a character."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT content FROM pending_messages WHERE character = ? ORDER BY timestamp",
            (character,),
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]


async def clear_pending_user_messages(character: str):
    """Clear pending messages after they've been addressed."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM pending_messages WHERE character = ?", (character,))
        await db.commit()

"""
Group Chat System for MomoTalk IRL.

Each bot independently monitors group chats it's been added to.
Bots decide whether to respond based on:
- Is the message relevant to their character?
- Random chance based on personality (some bots are chattier)
- Time-based activity (school schedule)
- Conversation cooldown (don't spam)

Bots communicate through a shared group_messages table in SQLite.
"""
import aiosqlite
import random
from datetime import datetime
from database import DB_PATH


async def init_group_tables():
    """Create group chat tables."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Log of all group messages for context
        await db.execute("""
            CREATE TABLE IF NOT EXISTS group_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                sender TEXT NOT NULL,
                content TEXT NOT NULL,
                reply_to_sender TEXT,
                reply_to_content TEXT,
                message_id INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Track when each bot last spoke in each group (cooldown)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS group_cooldowns (
                character TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                last_spoke DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (character, chat_id)
            )
        """)

        # Track when ANY bot last responded in each group (prevents spam)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS group_last_response (
                chat_id INTEGER PRIMARY KEY,
                last_response_time DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Track whether a specific chat message has already been claimed for response
        await db.execute("""
            CREATE TABLE IF NOT EXISTS group_message_responses (
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                claimed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chat_id, message_id)
            )
        """)

        # Prevent duplicate message inserts from multiple bot instances
        await db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_group_messages_chat_message_id
            ON group_messages (chat_id, message_id)
        """)

        await db.commit()


async def save_group_message(chat_id: int, sender: str, content: str, message_id: int = None, reply_to_sender: str = None, reply_to_content: str = None):
    """Save a message from the group chat."""
    await init_group_tables()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO group_messages (chat_id, sender, content, message_id, reply_to_sender, reply_to_content) VALUES (?, ?, ?, ?, ?, ?)",
            (chat_id, sender, content, message_id, reply_to_sender, reply_to_content),
        )
        await db.commit()


async def get_group_history(chat_id: int, limit: int = 30, exclude_message_id: int | None = None) -> list[dict]:
    """Get recent group chat history."""
    await init_group_tables()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if exclude_message_id is not None:
            cursor = await db.execute(
                "SELECT sender, content, reply_to_sender, reply_to_content, timestamp FROM group_messages WHERE chat_id = ? AND message_id != ? ORDER BY timestamp DESC LIMIT ?",
                (chat_id, exclude_message_id, limit),
            )
        else:
            cursor = await db.execute(
                "SELECT sender, content, reply_to_sender, reply_to_content, timestamp FROM group_messages WHERE chat_id = ? ORDER BY timestamp DESC LIMIT ?",
                (chat_id, limit),
            )
        rows = await cursor.fetchall()
        return [
            {
                "sender": row["sender"],
                "content": row["content"],
                "reply_to_sender": row["reply_to_sender"],
                "reply_to_content": row["reply_to_content"],
                "timestamp": row["timestamp"],
            }
            for row in reversed(rows)
        ]


async def get_seconds_since_last_spoke(character: str, chat_id: int) -> float | None:
    """How many seconds since this character last spoke in this group."""
    await init_group_tables()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT last_spoke FROM group_cooldowns WHERE character = ? AND chat_id = ?",
            (character, chat_id),
        )
        row = await cursor.fetchone()
        if not row:
            return None  # Never spoke
        last = datetime.fromisoformat(row[0])
        return (datetime.now() - last).total_seconds()


async def update_cooldown(character: str, chat_id: int):
    """Update when a character last spoke."""
    await init_group_tables()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO group_cooldowns (character, chat_id, last_spoke) VALUES (?, ?, ?)",
            (character, chat_id, datetime.now().isoformat()),
        )
        await db.commit()


async def get_seconds_since_group_last_response(chat_id: int) -> float | None:
    """How many seconds since ANY bot last responded in this group."""
    await init_group_tables()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT last_response_time FROM group_last_response WHERE chat_id = ?",
            (chat_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None  # No recent responses
        last = datetime.fromisoformat(row[0])
        return (datetime.now() - last).total_seconds()


async def update_group_last_response(chat_id: int):
    """Update the timestamp of the last group response."""
    await init_group_tables()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO group_last_response (chat_id, last_response_time) VALUES (?, ?)",
            (chat_id, datetime.now().isoformat()),
        )
        await db.commit()


async def claim_group_message_response(chat_id: int, message_id: int) -> bool:
    """Atomically claim a message so only one bot responds to it."""
    await init_group_tables()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT OR IGNORE INTO group_message_responses (chat_id, message_id) VALUES (?, ?)",
            (chat_id, message_id),
        )
        await db.commit()
        return cursor.rowcount == 1


def format_group_history_for_prompt(history: list[dict], character_name: str) -> str:
    """Format group chat history into a conversation log for Claude."""
    lines = []
    previous = None
    for msg in history:
        sender = msg["sender"]
        content = msg["content"]
        timestamp = None
        if msg.get("timestamp"):
            try:
                timestamp = datetime.fromisoformat(msg["timestamp"])
            except ValueError:
                timestamp = None

        if previous is not None:
            same_sender = previous["sender"] == sender
            same_content = previous["content"] == content
            if same_sender and same_content:
                if previous["timestamp"] and timestamp:
                    if (timestamp - previous["timestamp"]).total_seconds() < 10:
                        continue
                else:
                    continue

        if msg.get("reply_to_sender"):
            lines.append(f"{sender} (replying to {msg['reply_to_sender']}): {content}")
        else:
            lines.append(f"{sender}: {content}")

        previous = {
            "sender": sender,
            "content": content,
            "timestamp": timestamp,
        }
    return "\n".join(lines)


def infer_reply_target(history: list[dict], user_text: str) -> tuple[str | None, str | None]:
    """Infer who Sensei is replying to from recent history and the current text."""
    if not history:
        return None, None

    lower_text = user_text.lower()
    text_length = len(user_text.strip())
    # If Sensei mentions a name directly, use that person
    for msg in reversed(history):
        sender = msg["sender"]
        if sender.lower() == "sensei":
            continue
        if sender.lower() in lower_text:
            return sender, msg["content"]

    # If the user message looks like a direct question, assume it is replying to the most recent speaker.
    question_starters = ("what", "who", "when", "where", "how", "why", "is", "are", "do", "does", "did", "can", "could", "should", "would")
    last = history[-1]
    if lower_text.strip().startswith(question_starters) or lower_text.strip().endswith("?"):
        if last["sender"].lower() != "sensei":
            return last["sender"], last["content"]

    # If the message is short (< 50 chars) and the last speaker is not Sensei, infer a reply to them
    if text_length < 50 and last["sender"].lower() != "sensei":
        return last["sender"], last["content"]

    return None, None


def should_respond_to_group(character_name: str, sender: str, content: str, chattiness: float = 0.3) -> bool:
    """
    Decide if a character should respond to a group message.
    
    chattiness: 0.0-1.0, how likely they are to jump in.
    Returns True if they should respond.
    """
    # Never respond to own messages
    if sender.lower() == character_name.lower():
        return False

    # Higher chance if mentioned by name
    if character_name.lower() in content.lower():
        return min(chattiness * 3, 0.95)  > random.random()

    # Higher chance if responding to Sensei
    if sender == "Sensei":
        return min(chattiness * 2, 0.8) > random.random()

    # Base chance
    return chattiness > random.random()


# Chattiness levels per character personality
CHATTINESS = {
    "momoi": 0.55,     # Very chatty, always jumping in
    "midori": 0.40,    # Responds to correct Momoi
    "alice": 0.35,     # Curious, asks questions
    "yuzu": 0.15,      # Very shy, rarely speaks
    "hina": 0.35,      # Speaks when needed, authoritative
    "ako": 0.50,       # Eager, especially about Hina
    "mutsuki": 0.40,   # Drops in with chaos
    "kayoko": 0.25,    # Quiet, occasional gloomy comment
    "arona": 0.40,     # Helpful, eager
    "plana": 0.20,     # Only speaks when something is inefficient
    "hoshino": 0.15,   # Too lazy to type usually
    "yuuka": 0.30,     # Speaks up about money/budgets
    "aru": 0.45,       # Can't resist jumping in with plans
    "hanako": 0.50,    # Nosy, wants in on everything
    "shioko": 0.15,    # Minimal words
    "reisa": 0.25,     # Speaks about competition/speed
    "ui": 0.25,        # Gentle encouragement
    "rio": 0.20,       # Only when intel-relevant
}

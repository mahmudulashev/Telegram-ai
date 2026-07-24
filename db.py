import aiosqlite
import logging
from typing import Optional, Dict, Any, List
from config import DB_PATH, ENABLE_TELEGRAM_BRAIN_BACKUP

logger = logging.getLogger(__name__)

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_msg_id INTEGER UNIQUE,
    draft_msg_id INTEGER,
    user_id INTEGER NOT NULL,
    user_msg_id INTEGER NOT NULL,
    first_name TEXT,
    last_name TEXT,
    username TEXT,
    bio TEXT,
    incoming_text TEXT,
    category TEXT,
    summary TEXT,
    status TEXT DEFAULT 'pending',
    response_text TEXT,
    draft_text TEXT,
    schedule_time INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS user_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tone_of_voice TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS contact_context (
    user_id INTEGER PRIMARY KEY,
    relationship_context TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS web_chat_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    draft_text TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    fact TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS autopilot (
    user_id INTEGER PRIMARY KEY,
    expires_at INTEGER NOT NULL
);
"""

async def init_db():
    """Initialize SQLite database and create tables."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(CREATE_TABLES_SQL)
        # Attempt to migrate existing database seamlessly
        try:
            await db.execute("ALTER TABLE messages ADD COLUMN draft_text TEXT")
            await db.execute("ALTER TABLE messages ADD COLUMN schedule_time INTEGER")
            await db.execute("ALTER TABLE messages ADD COLUMN draft_msg_id INTEGER")
        except Exception:
            pass # Columns already exist
        await db.commit()
    logger.info("Database initialized successfully.")

async def save_incoming_message(
    admin_msg_id: int,
    user_id: int,
    user_msg_id: int,
    first_name: Optional[str],
    last_name: Optional[str],
    username: Optional[str],
    bio: Optional[str],
    incoming_text: str,
    category: str,
    summary: str
) -> bool:
    """Save incoming analyzed message details and link to admin notification ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                """
                INSERT INTO messages (
                    admin_msg_id, user_id, user_msg_id, first_name, last_name, 
                    username, bio, incoming_text, category, summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    admin_msg_id, user_id, user_msg_id, first_name, last_name,
                    username, bio, incoming_text, category, summary
                )
            )
            await db.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to save message to DB: {e}")
            return False

async def save_historical_message(
    user_id: int,
    user_msg_id: int,
    first_name: Optional[str],
    last_name: Optional[str],
    username: Optional[str],
    incoming_text: str,
    category: str,
    summary: str,
    status: str = 'replied',
    response_text: Optional[str] = None
) -> bool:
    """Save a historical Telegram message into DB safely without duplicate admin_msg_id."""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            async with db.execute(
                "SELECT id FROM messages WHERE user_id = ? AND user_msg_id = ?",
                (user_id, user_msg_id)
            ) as cursor:
                if await cursor.fetchone():
                    return False
            
            dummy_admin_msg_id = -(abs(user_id) * 1000000 + user_msg_id)
            
            await db.execute(
                """
                INSERT INTO messages (
                    admin_msg_id, user_id, user_msg_id, first_name, last_name, 
                    username, incoming_text, category, summary, status, response_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dummy_admin_msg_id, user_id, user_msg_id, first_name, last_name,
                    username, incoming_text, category, summary, status, response_text
                )
            )
            await db.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to save historical message: {e}")
            return False

async def get_message_by_admin_msg_id(admin_msg_id: int) -> Optional[Dict[str, Any]]:
    """Retrieve message context using the admin chat notification message ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM messages WHERE admin_msg_id = ?", (admin_msg_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None

async def get_message_by_id(msg_id: int) -> Optional[Dict[str, Any]]:
    """Retrieve message context by DB primary ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM messages WHERE id = ?", (msg_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None

async def get_message_by_draft_msg_id(draft_msg_id: int) -> Optional[Dict[str, Any]]:
    """Retrieve message context using the draft message ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM messages WHERE draft_msg_id = ?", (draft_msg_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None

async def save_message_draft(admin_msg_id: int, draft_msg_id: int, draft_text: str, schedule_time: Optional[int] = None) -> bool:
    """Save the AI generated draft, draft msg ID, and optional schedule time to the DB."""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                """
                UPDATE messages 
                SET status = 'drafted', draft_msg_id = ?, draft_text = ?, schedule_time = ?
                WHERE admin_msg_id = ?
                """,
                (draft_msg_id, draft_text, schedule_time, admin_msg_id)
            )
            await db.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to save draft to DB: {e}")
            return False

async def update_message_response(admin_msg_id: int, response_text: str) -> bool:
    """Update message status to replied and record generated AI response."""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                """
                UPDATE messages 
                SET status = 'replied', response_text = ? 
                WHERE admin_msg_id = ?
                """,
                (response_text, admin_msg_id)
            )
            await db.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to update message status in DB: {e}")
            return False

async def cancel_message_draft(admin_msg_id: int) -> bool:
    """Cancel a drafted message."""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                """
                UPDATE messages 
                SET status = 'pending', draft_text = NULL, schedule_time = NULL
                WHERE admin_msg_id = ?
                """,
                (admin_msg_id,)
            )
            await db.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to cancel draft in DB: {e}")
            return False

async def get_all_messages(limit: int = 50) -> List[Dict[str, Any]]:
    """Get latest messages for the Web UI dashboard."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM messages ORDER BY id DESC LIMIT ?", (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def get_stats() -> Dict[str, Any]:
    """Get message statistics and breakdown for Dashboard analytics."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM messages") as cursor:
            total = (await cursor.fetchone())[0]

        async with db.execute("SELECT COUNT(*) FROM messages WHERE status = 'pending'") as cursor:
            pending = (await cursor.fetchone())[0]

        async with db.execute("SELECT COUNT(*) FROM messages WHERE status = 'replied'") as cursor:
            replied = (await cursor.fetchone())[0]

        categories = {}
        for cat in ["Urgent", "Inquiry", "Offer", "Spam", "Casual"]:
            async with db.execute("SELECT COUNT(*) FROM messages WHERE category = ?", (cat,)) as cursor:
                categories[cat] = (await cursor.fetchone())[0]

        return {
            "total_messages": total,
            "pending_count": pending,
            "replied_count": replied,
            "categories": categories
        }

async def save_user_profile(tone_of_voice: str) -> bool:
    """Save the global tone of voice profile generated from chat history."""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            # We only need one global profile, so we use ID 1 and replace if exists
            await db.execute(
                """
                INSERT OR REPLACE INTO user_profile (id, tone_of_voice, updated_at)
                VALUES (1, ?, CURRENT_TIMESTAMP)
                """,
                (tone_of_voice,)
            )
            await db.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to save user profile: {e}")
            return False

async def get_user_profile() -> Optional[str]:
    """Retrieve the global tone of voice profile."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT tone_of_voice FROM user_profile WHERE id = 1") as cursor:
            row = await cursor.fetchone()
            if row:
                return row[0]
            return None

async def save_contact_context(user_id: int, relationship_context: str) -> bool:
    """Save the specific relationship context for a user."""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                """
                INSERT OR REPLACE INTO contact_context (user_id, relationship_context, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                """,
                (user_id, relationship_context)
            )
            await db.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to save contact context for {user_id}: {e}")
            return False

async def get_contact_context(user_id: int) -> Optional[str]:
    """Retrieve the specific relationship context for a user."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT relationship_context FROM contact_context WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return row[0]
            return None

_pyrogram_client = None

def set_db_client(client):
    global _pyrogram_client
    _pyrogram_client = client

async def add_memory(user_id: int, fact: str) -> bool:
    """Save a newly extracted memory fact to the database and backup to Telegram."""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            async with db.execute("SELECT id FROM memories WHERE user_id = ? AND fact = ?", (user_id, fact)) as cursor:
                if await cursor.fetchone():
                    return False
            await db.execute(
                """
                INSERT INTO memories (user_id, fact)
                VALUES (?, ?)
                """,
                (user_id, fact)
            )
            await db.commit()

            if _pyrogram_client and ENABLE_TELEGRAM_BRAIN_BACKUP:
                try:
                    await _pyrogram_client.send_message("me", f"🧠 <b>AI MEMORY BACKUP</b> #AI_BRAIN_BACKUP\nUSER:{user_id}\nFACT:{fact}")
                except Exception as e:
                    logger.debug(f"Failed to backup memory to Telegram: {e}")
            return True
        except Exception as e:
            logger.error(f"Failed to save memory for {user_id}: {e}")
            return False

async def restore_memories_from_telegram(client):
    """Restore memories from Telegram Saved Messages backup."""
    if not client:
        return
    try:
        logger.info("Restoring AI Memories from Telegram Saved Messages backup...")
        restored = 0
        async for msg in client.get_chat_history("me", limit=100):
            if msg.text and "#AI_BRAIN_BACKUP" in msg.text:
                lines = msg.text.split("\n")
                uid = 0
                fact = ""
                for line in lines:
                    if line.startswith("USER:"):
                        try: uid = int(line.replace("USER:", "").strip())
                        except: pass
                    elif line.startswith("FACT:"):
                        fact = line.replace("FACT:", "").strip()
                if fact:
                    saved = await add_memory(uid, fact)
                    if saved: restored += 1
        logger.info(f"Restored {restored} memories from Telegram cloud backup.")
    except Exception as e:
        logger.warning(f"Error restoring memories from Telegram: {e}")

async def get_memories(user_id: int, limit: int = 10) -> List[str]:
    """Retrieve recent memories associated with a specific user."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT fact FROM memories WHERE user_id = ? ORDER BY id DESC LIMIT ?", 
            (user_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

async def add_web_chat_message(message_id: int, role: str, content: str, draft_text: Optional[str] = None) -> bool:
    """Save a message to the web chat history."""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                """
                INSERT INTO web_chat_history (message_id, role, content, draft_text)
                VALUES (?, ?, ?, ?)
                """,
                (message_id, role, content, draft_text)
            )
            await db.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to save web chat message: {e}")
            return False

async def get_web_chat_history(message_id: int) -> List[Dict[str, Any]]:
    """Retrieve web chat history for a specific incoming message."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT role, content, draft_text, created_at FROM web_chat_history WHERE message_id = ? ORDER BY id ASC", 
            (message_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def delete_memory(memory_id: int) -> bool:
    """Delete a specific memory by its ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            await db.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to delete memory {memory_id}: {e}")
            return False

async def get_all_admin_memories() -> List[Dict[str, Any]]:
    """Retrieve all memories saved for the Admin (user_id = 0)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, fact, created_at FROM memories WHERE user_id = 0 ORDER BY id DESC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def set_autopilot(user_id: int, duration_hours: int) -> bool:
    """Enable autopilot for a user for a specific duration in hours."""
    import time
    expires_at = int(time.time()) + (duration_hours * 3600)
    return await set_autopilot_until(user_id, expires_at)

async def set_autopilot_until(user_id: int, expires_at_timestamp: int) -> bool:
    """Enable autopilot for a user until an exact unix timestamp."""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                """
                INSERT OR REPLACE INTO autopilot (user_id, expires_at)
                VALUES (?, ?)
                """,
                (user_id, expires_at_timestamp)
            )
            await db.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to set autopilot until timestamp for {user_id}: {e}")
            return False

async def get_active_autopilots() -> Dict[int, Dict[str, Any]]:
    """Retrieve all active autopilot sessions with formatted expiration date."""
    import time, datetime
    current_time = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT user_id, expires_at FROM autopilot WHERE expires_at > ?",
            (current_time,)
        ) as cursor:
            rows = await cursor.fetchall()
            result = {}
            for row in rows:
                uid = row['user_id']
                exp = row['expires_at']
                dt = datetime.datetime.fromtimestamp(exp)
                result[uid] = {
                    "user_id": uid,
                    "expires_at": exp,
                    "formatted_expiry": dt.strftime('%d-%b %H:%M')
                }
            return result

async def is_autopilot_active(user_id: int) -> bool:
    """Check if autopilot is active for the given user OR globally for all users (user_id = 0)."""
    import time
    current_time = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT expires_at FROM autopilot WHERE user_id = ? OR user_id = 0 ORDER BY expires_at DESC LIMIT 1", 
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                if row[0] > current_time:
                    return True
                else:
                    await db.execute("DELETE FROM autopilot WHERE user_id = ?", (user_id,))
                    await db.commit()
            return False

async def disable_autopilot(user_id: int) -> bool:
    """Manually disable autopilot for a user (or global autopilot if user_id=0)."""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("DELETE FROM autopilot WHERE user_id = ?", (user_id,))
            await db.commit()
            return True
        except Exception as e:
            return False

async def set_global_autopilot(enabled: bool, hours: int = 87600) -> bool:
    """Enable or disable global autopilot for ALL chats (user_id = 0)."""
    if enabled:
        import time
        expires_at = int(time.time()) + (hours * 3600)
        return await set_autopilot_until(0, expires_at)
    else:
        return await disable_autopilot(0)

async def is_global_autopilot_active() -> bool:
    """Check if global autopilot is currently active."""
    import time
    current_time = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT expires_at FROM autopilot WHERE user_id = 0", 
        ) as cursor:
            row = await cursor.fetchone()
            return bool(row and row[0] > current_time)

async def clear_historical_messages() -> int:
    """Clean up dummy imported history messages from the main feed."""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            async with db.execute("DELETE FROM messages WHERE admin_msg_id < 0") as cursor:
                count = cursor.rowcount
                await db.commit()
                return count
        except Exception as e:
            logger.error(f"Failed to clear historical messages: {e}")
            return 0

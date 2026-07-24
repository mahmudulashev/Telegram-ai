import os
import sys
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Telegram API Credentials\
API_ID_RAW = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

if not API_ID_RAW or not API_HASH:
    print("❌ ERROR: API_ID and API_HASH must be set in your .env file!")
    print("👉 Get them from https://my.telegram.org")
    sys.exit(1)

try:
    API_ID = int(API_ID_RAW)
except ValueError:
    print("❌ ERROR: API_ID must be an integer!")
    sys.exit(1)

# OpenAI / LLM Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    print("⚠️ WARNING: OPENAI_API_KEY is not set in your .env file.")

OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Admin Chat Configuration
ADMIN_CHAT_RAW = os.getenv("ADMIN_CHAT_ID", "me").strip()
if ADMIN_CHAT_RAW.lower() == "me":
    ADMIN_CHAT_ID = "me"
else:
    try:
        ADMIN_CHAT_ID = int(ADMIN_CHAT_RAW)
    except ValueError:
        ADMIN_CHAT_ID = ADMIN_CHAT_RAW

# Userbot Settings
SESSION_NAME = os.getenv("SESSION_NAME", "userbot_session")
DB_PATH = os.getenv("DB_PATH", "userbot.db")
ENABLE_TELEGRAM_BRAIN_BACKUP = os.getenv("ENABLE_TELEGRAM_BRAIN_BACKUP", "false").lower() == "true"
ENABLE_TELEGRAM_NOTIFICATIONS = os.getenv("ENABLE_TELEGRAM_NOTIFICATIONS", "false").lower() == "true"



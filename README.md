# 🤖 Personal Telegram AI Agent (Userbot)

An intelligent, AI-powered Personal Telegram Assistant built with **Pyrogram**, **OpenAI API**, and **SQLite**. 

This userbot monitors private Telegram messages, analyzes sender identities and intent, categorizes incoming messages, sends structured notification cards to your designated **Admin Chat** (e.g. Saved Messages), and allows you to reply with brief instructions to generate natural **Uzbek Tone-of-Voice** responses directly sent on your behalf.

---

## 🌟 Key Features

- **🛡️ Private Message Monitoring:** Intercepts private direct messages while ignoring channels, groups, and bots.
- **🔍 Stage 1 AI Analysis (Profiling & Classification):**
  - Extracts sender name, bio, and role.
  - Detects sender intent and goal.
  - Categorizes into: `🔴 Urgent`, `🔵 Inquiry`, `🟢 Offer`, `⚠️ Spam`, or `🟡 Casual`.
  - Generates a 1-2 sentence message summary.
- **📩 Rich Telegram Card Notifications:** Posts clean HTML cards to your Admin Chat with all analyzed insights.
- **🇺🇿 Stage 2 Human-in-the-Loop Uzbek Response Generation:**
  - Simply reply to the notification message in Admin Chat with brief instructions (e.g. *"Say I'm busy today, let's talk tomorrow at 10 AM"*).
  - The AI formats your instruction into a concise, natural, authentic Uzbek response matching your Tone of Voice (1-2 emojis max, clear everyday speech).
- **💾 SQLite Context Tracking:** Remembers incoming messages and admin notification mappings.

---

## 📁 Project Structure

```
.
├── config.py          # Environment variables & setting loaders
├── ai_agent.py        # OpenAI LLM integration (Stage 1 Analysis & Stage 2 Uzbek Reply)
├── db.py              # Asynchronous SQLite storage (aiosqlite)
├── main.py            # Pyrogram client setup, event handlers & startup logic
├── requirements.txt   # Required Python dependencies
├── .env.example       # Environment variables template
└── README.md          # Complete documentation & setup guide
```

---

## 🚀 Getting Started

### 1. Prerequisites

- Python 3.9 or higher installed on your system.
- Telegram Account.
- OpenAI API Key (or compatible Gemini API Key).

---

### 2. How to Obtain Telegram API_ID & API_HASH

1. Visit [https://my.telegram.org](https://my.telegram.org) and log in with your Telegram phone number.
2. Click on **"API Development Tools"**.
3. Create a new application (Fill in an App Title and Short Name, e.g., `MyPersonalUserbot`).
4. Copy your **`App api_id`** (an integer) and **`App api_hash`** (a 32-character string).

---

### 3. Installation

Clone or download the project folder, then navigate to the directory:

```bash
cd "Telegram ai"
```

Create a Python virtual environment and activate it:

```bash
# On macOS / Linux:
python3 -m venv venv
source venv/bin/activate

# On Windows:
python -m venv venv
venv\Scripts\activate
```

Install required dependencies:

```bash
pip install -r requirements.txt
```

---

### 4. Configuration (.env setup)

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Edit `.env` with your preferred text editor and fill in your values:

```env
# Telegram API Credentials (from https://my.telegram.org)
API_ID=1234567
API_HASH=abcdef1234567890abcdef1234567890

# OpenAI API Key
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxxxxxx
OPENAI_MODEL=gpt-4o-mini

# Admin Chat Settings
# Use "me" to receive notifications in your Telegram "Saved Messages",
# or enter a numerical Chat/User ID (e.g. 123456789)
ADMIN_CHAT_ID=me

# Pyrogram Session Name
SESSION_NAME=userbot_session
```

---

### 5. Running the Userbot

Start the application:

```bash
python main.py
```

> ⚠️ **First Time Login Note:**
> On the first launch, Pyrogram will prompt you in the terminal for your **phone number** (in international format, e.g. `+998901234567`) and the **login code (OTP)** sent to your Telegram app.
> Once authenticated, Pyrogram saves a session file (`userbot_session.session`) locally, so you won't need to log in again.

---

## 🎯 Usage & Workflow

1. **Incoming Message:** When someone sends you a private Telegram message, the bot automatically extracts their details, fetches their bio, and runs AI Stage 1 analysis.
2. **Notification Card:** You will receive a notification card in your **Saved Messages** (or designated Admin Chat):

   ```text
   📥 NEW PRIVATE MESSAGE
   👤 Sender: Alisher ( @alisher_dev )
   💼 Bio / Role: Backend Developer at Tech Co
   🏷️ Category: 🔵 INQUIRY
   🎯 Intent: Asking for a meeting regarding project updates.

   📝 Summary: Alisher is asking if you are free for a quick call today.

   💬 Original Message:
   "Salom! Bugun loyiha bo'yicha 15 daqiqaga gaplashib olsak bo'ladimi?"

   💡 Reply to this notification message with your brief instructions to send an AI response!
   ```

3. **Human-in-the-Loop Reply:** Reply directly to that notification message in your Saved Messages with your brief instructions, for example:
   > *"Bugun bandman, ertaga soat 11:00 da gaplashamiz degan javob yoz"*

4. **Automatic Response Sent:** The AI generates an authentic, friendly Uzbek response and sends it to Alisher:
   > *"Salom! Bugun afsuski bo'sh emasdim. Ertaga soat 11:00 da gaplashsak qanday bo'ladi? 👍"*

---

## 🛠️ Customization & Tone of Voice

You can adjust the system prompts and Tone of Voice guidelines inside `ai_agent.py`:
- **`STAGE1_SYSTEM_PROMPT`**: Customize categories or extraction rules.
- **`STAGE2_SYSTEM_PROMPT`**: Tweak language rules, formality levels, or emoji count.

---

## 📄 License

MIT License. Free to use and modify for personal automation!

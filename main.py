import os
import asyncio
import logging
import base64
import uvicorn
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import RPCError

import config
import db
import ai_agent
import learner
from web_app import app as fastapi_app, set_pyrogram_client

# Configure logging format
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("Userbot")

# Category Badge Helper
CATEGORY_BADGES = {
    "Urgent": "🔴 <b>SHOSHILINCH (URGENT)</b>",
    "Inquiry": "🔵 <b>SAVOL / SO'ROV (INQUIRY)</b>",
    "Offer": "🟢 <b>TAKLIF (OFFER)</b>",
    "Spam": "⚠️ <b>SPAM</b>",
    "Casual": "🟡 <b>SUHBAT / OILAVIY (CASUAL)</b>"
}

# Restore Telegram Pyrogram session from Environment Variable if deployed on Cloud (Koyeb/Render)
session_file = f"{config.SESSION_NAME}.session"
session_b64_env = os.getenv("SESSION_BASE64")
session_str_env = os.getenv("SESSION_STRING")

if session_b64_env:
    try:
        logging.info("Restoring Pyrogram session from SESSION_BASE64 environment variable...")
        with open(session_file, "wb") as f:
            f.write(base64.b64decode(session_b64_env.strip()))
        logging.info("Session file restored successfully from SESSION_BASE64!")
    except Exception as e:
        logging.error(f"Failed to restore session from SESSION_BASE64: {e}")
elif not session_str_env and not os.path.exists(session_file):
    logging.warning("⚠️ WARNING: SESSION_BASE64 or SESSION_STRING environment variable is NOT set on Cloud server!")

# Initialize Pyrogram Userbot Client
app = Client(
    name=config.SESSION_NAME,
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    session_string=session_str_env if session_str_env else None
)

@app.on_message(filters.chat(config.ADMIN_CHAT_ID) & filters.command("learn", prefixes=["/", ".", "!"]) & ~filters.bot)
async def handle_learn_command(client: Client, message: Message):
    """
    Handler to initiate the AI chat history learning process.
    """
    status_msg = await message.reply_text("⏳ O'rganish jarayoni boshlanmoqda...", parse_mode=filters.enums.ParseMode.HTML)
    
    # Run in background to avoid blocking the client
    asyncio.create_task(learner.run_learning_process(client, status_msg))

@app.on_message(filters.private & ~filters.me & ~filters.bot & ~filters.service)
async def handle_incoming_private_message(client: Client, message: Message):
    """
    Handler for incoming private text & photo messages.
    Extracts text, photos, contact status, bio, runs Uzbek & Vision AI Stage 1 analysis,
    saves state to DB, and sends a formatted card to Admin Chat.
    """
    user = message.from_user
    if not user:
        return

    # Extract text content (either direct text or photo caption)
    incoming_text = message.text or message.caption or ""

    # Download and process photo if present
    image_b64 = None
    if message.photo:
        try:
            logger.info("Photo detected in incoming message. Downloading for AI Vision analysis...")
            photo_bytes = await client.download_media(message, in_memory=True)
            if photo_bytes:
                image_b64 = base64.b64encode(photo_bytes.getvalue()).decode('utf-8')
        except Exception as e:
            logger.warning(f"Failed to download/process photo for Vision AI: {e}")

    # Check if message is a reply to another message (Telegram Reply / Quote)
    reply_info_str = ""
    if message.reply_to_message:
        reply_msg = message.reply_to_message
        is_reply_outgoing = reply_msg.outgoing or (reply_msg.from_user and getattr(reply_msg.from_user, 'is_self', False))
        reply_sender = "Sizning (Mahmudning) xabaringiz" if is_reply_outgoing else "Suhbatdosh xabari"
        reply_content = reply_msg.text or reply_msg.caption or "[Rasm/Media]"
        reply_info_str = f"➡️ [USHBU XABARGA JAVOB SIFATIDA YOZILGAN (REPLY TO '{reply_sender}': '{reply_content}')]\n"
        
        # If the replied-to message has a photo and current message has no photo, download replied photo for Vision AI!
        if not image_b64 and reply_msg.photo:
            try:
                logger.info("Photo detected in replied-to message. Downloading for AI Vision analysis...")
                photo_bytes = await client.download_media(reply_msg, in_memory=True)
                if photo_bytes:
                    image_b64 = base64.b64encode(photo_bytes.getvalue()).decode('utf-8')
            except Exception as e:
                logger.warning(f"Failed to download replied photo for Vision AI: {e}")

    incoming_text = f"{reply_info_str}{incoming_text}".strip()

    # If neither text nor photo is present, skip
    if not incoming_text and not image_b64:
        return

    logger.info(f"Incoming message from user ID {user.id} ({user.first_name})")

    # Fetch User Bio via Pyrogram API
    bio = "Bio kiritilmagan"
    try:
        chat_info = await client.get_chat(user.id)
        if chat_info.bio:
            bio = chat_info.bio
    except Exception as e:
        logger.warning(f"Could not fetch bio for user {user.id}: {e}")

    user_info = {
        "user_id": user.id,
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
        "username": user.username or "",
        "is_contact": getattr(user, 'is_contact', False),
        "bio": bio
    }

    # Fetch recent context (last 25 messages with timestamps) for AI
    recent_context = ""
    try:
        history = []
        async for msg in client.get_chat_history(user.id, limit=25):
            if msg.id != message.id: # Skip current message to avoid duplication
                is_me = msg.outgoing or (msg.from_user and getattr(msg.from_user, 'is_self', False))
                sender = "Siz (Mahmud)" if is_me else "Suhbatdosh"
                time_str = msg.date.strftime("%H:%M") if msg.date else ""
                text = msg.text or msg.caption or "[Media]"
                history.append(f"[{time_str}] {sender}: {text}")
        if history:
            history.reverse()
            recent_context = "\n".join(history)
    except Exception as e:
        logger.warning(f"Could not fetch recent history for context: {e}")

    # Display Text for Card
    display_msg = incoming_text if incoming_text else "🖼️ [Rasm yuborildi]"
    if message.photo and incoming_text:
        display_msg = f"🖼️ [Rasm va matn]: {incoming_text}"

    # ---------------- AUTOPILOT CHECK ----------------
    is_autopilot = await db.is_autopilot_active(user.id)
    
    if is_autopilot:
        # Fetch recent context and memories for autopilot AI analysis
        recent_context = ""
        try:
            history = []
            async for msg in client.get_chat_history(user.id, limit=25):
                if msg.id != message.id:
                    is_me = msg.outgoing or (msg.from_user and getattr(msg.from_user, 'is_self', False))
                    sender = "Siz (Mahmud)" if is_me else "Suhbatdosh"
                    time_str = msg.date.strftime("%H:%M") if msg.date else ""
                    text = msg.text or msg.caption or "[Media]"
                    history.append(f"[{time_str}] {sender}: {text}")
            if history:
                history.reverse()
                recent_context = "\n".join(history)
        except Exception as e:
            logger.warning(f"Could not fetch recent history for context: {e}")

        past_memories = await db.get_memories(user.id, limit=10)
        
        analysis = await ai_agent.analyze_message(
            user_info=user_info, 
            message_text=incoming_text, 
            image_b64=image_b64,
            recent_context=recent_context,
            past_memories=past_memories
        )

        category = analysis.get("category", "Casual")
        report = analysis.get('conversational_report', incoming_text)

        if category == "Urgent":
            await db.disable_autopilot(user.id)
            is_autopilot = False
            if config.ENABLE_TELEGRAM_NOTIFICATIONS:
                try:
                    await client.send_message(
                        chat_id=config.ADMIN_CHAT_ID,
                        text=f"🚨 <b>AVTOPILOT TO'XTATILDI: SHOSHILINCH XABAR!</b>\n<i>Foydalanuvchi '{user.first_name or ''}' dan shoshilinch (Urgent) xabar kelgani uchun avtopilot bu odam uchun darhol o'chirildi!</i>",
                        parse_mode=filters.enums.ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Urgent override notification failed: {e}")

        if is_autopilot:
            dummy_admin_msg_id = -(message.id)
            await db.save_incoming_message(
                admin_msg_id=dummy_admin_msg_id,
                user_id=user.id,
                user_msg_id=message.id,
                first_name=user.first_name,
                last_name=user.last_name,
                username=user.username,
                bio=bio,
                incoming_text=display_msg,
                category=category,
                summary=report
            )
            msg_context = await db.get_message_by_admin_msg_id(dummy_admin_msg_id)
            admin_memories = await db.get_all_admin_memories()
            admin_memories_texts = [m['fact'] for m in admin_memories]

            ai_response = await ai_agent.generate_response(
                admin_instruction="Siz hozir AVTOPILOT rejimidasiz. Mahmud hozir band. Suhbatdosh bilan mantiqan to'g'ri, qoidalar va xotiralarga tayangan holda mustaqil javob yozib yuboring.",
                context=msg_context,
                recent_context=recent_context,
                past_memories=past_memories,
                admin_memories=admin_memories_texts
            )
            
            draft_text = ai_response.get("draft_text", "")
            if draft_text:
                try:
                    await client.send_message(chat_id=user.id, text=draft_text)
                    await db.update_message_response(dummy_admin_msg_id, draft_text)
                    logger.info(f"Autopilot sent response to {user.id}")
                except Exception as e:
                    logger.error(f"Autopilot failed to send message: {e}")
            return # Skip manual flow

    # ---------------- MANUAL / ON-DEMAND FLOW ----------------
    # Save incoming message directly to SQLite database WITHOUT auto LLM analysis
    category = "Casual"
    report = display_msg

    admin_msg_id = -(abs(user.id) * 1000000 + message.id)
    if config.ENABLE_TELEGRAM_NOTIFICATIONS:
        notification_card = (
            f"🔔 <b>Yangi xabar:</b>\n\n"
            f"<i>{report}</i>\n\n"
            f"💬 Bunga nima deb javob qaytaray? Qisqacha aytsangiz, o'zim chiroyli qilib yozib yuboraman!"
        )
        try:
            admin_msg = await client.send_message(
                chat_id=config.ADMIN_CHAT_ID,
                text=notification_card,
                parse_mode=filters.enums.ParseMode.HTML
            )
            admin_msg_id = admin_msg.id
            logger.info(f"Notification sent to Admin Chat. Admin Message ID: {admin_msg.id}")
        except RPCError as e:
            logger.error(f"Failed to send admin notification message: {e}")
        except Exception as e:
            logger.error(f"Unexpected error in incoming message handler: {e}")

    await db.save_incoming_message(
        admin_msg_id=admin_msg_id,
        user_id=user.id,
        user_msg_id=message.id,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        bio=bio,
        incoming_text=display_msg,
        category=category,
        summary=report
    )

@app.on_message(filters.chat(config.ADMIN_CHAT_ID) & filters.reply & ~filters.bot)
async def handle_admin_reply(client: Client, message: Message):
    """
    Handler for Admin Chat replies.
    Can either trigger AI drafting, or confirm/cancel a drafted message.
    """
    if not message.text or not message.reply_to_message:
        return

    admin_instruction = message.text.strip()
    admin_instruction_lower = admin_instruction.lower()
    replied_msg_id = message.reply_to_message.id

    # 1. Check if the admin is replying to a DRAFT message
    draft_context = await db.get_message_by_draft_msg_id(replied_msg_id)
    if draft_context and draft_context.get('status') == 'drafted':
        # Check if the instruction is a confirmation command
        if admin_instruction_lower in ["ok", "yubor", "send", "tasdiqlayman"]:
            target_user_id = draft_context['user_id']
            target_msg_id = draft_context['user_msg_id']
            draft_text = draft_context['draft_text']
            schedule_time = draft_context['schedule_time']
            
            try:
                import datetime
                if schedule_time:
                    dt = datetime.datetime.fromtimestamp(schedule_time)
                    await client.send_message(
                        chat_id=target_user_id, 
                        text=draft_text, 
                        reply_to_message_id=target_msg_id,
                        schedule_date=dt
                    )
                    await message.reply_text(f"✅ <b>Xabar muvaffaqiyatli rejalashtirildi!</b> ({dt.strftime('%Y-%m-%d %H:%M')})", parse_mode=filters.enums.ParseMode.HTML)
                else:
                    await client.send_message(
                        chat_id=target_user_id, 
                        text=draft_text, 
                        reply_to_message_id=target_msg_id
                    )
                    await message.reply_text("✅ <b>Xabar muvaffaqiyatli yuborildi!</b>", parse_mode=filters.enums.ParseMode.HTML)
                
                await db.update_message_response(draft_context['admin_msg_id'], draft_text)
            except Exception as e:
                logger.error(f"Failed to send/schedule draft: {e}")
                await message.reply_text(f"❌ <b>Xatolik yuz berdi:</b> {e}", parse_mode=filters.enums.ParseMode.HTML)
            return
        elif admin_instruction_lower in ["bekor", "yoq", "cancel", "o'chir"]:
            await db.cancel_message_draft(draft_context['admin_msg_id'])
            await message.reply_text("❌ <b>Qoralama bekor qilindi.</b>", parse_mode=filters.enums.ParseMode.HTML)
            return
        
    # 2. If it's not a confirmation, then it's an instruction for the AI.
    # It could be a reply to the original notification, or a follow-up instruction to a draft.
    msg_context = draft_context if draft_context else await db.get_message_by_admin_msg_id(replied_msg_id)
    
    if not msg_context:
        return # Not related to our bot's messages

    target_user_id = msg_context["user_id"]
    admin_msg_id = msg_context["admin_msg_id"]

    # Send temporary status notification to Admin
    status_msg = await message.reply_text("⏳ <i>Kotiba tahlil qilmoqda...</i>", parse_mode=filters.enums.ParseMode.HTML)

    # Fetch recent context for generating an accurate response (Last 20 messages)
    recent_context = ""
    try:
        history = []
        async for msg in client.get_chat_history(target_user_id, limit=25):
            is_me = msg.outgoing or (msg.from_user and getattr(msg.from_user, 'is_self', False))
            sender = "Siz (Mahmud)" if is_me else "Suhbatdosh"
            time_str = msg.date.strftime("%H:%M") if msg.date else ""
            text = msg.text or msg.caption or "[Media]"
            history.append(f"[{time_str}] {sender}: {text}")
        if history:
            history.reverse()
            recent_context = "\n".join(history)
    except Exception as e:
        logger.warning(f"Could not fetch recent history for Stage 2: {e}")

    # Fetch past memories for Response Generation
    past_memories = await db.get_memories(target_user_id, limit=10)
    admin_memories = await db.get_all_admin_memories()
    admin_memories_texts = [m['fact'] for m in admin_memories]

    # Stage 2 AI Response Generation (Drafting)
    ai_response = await ai_agent.generate_response(
        admin_instruction=admin_instruction, 
        context=msg_context,
        recent_context=recent_context,
        past_memories=past_memories,
        admin_memories=admin_memories_texts
    )

    # Save any new admin facts
    new_admin_facts = ai_response.get("new_admin_facts_to_remember", [])
    for fact in new_admin_facts:
        if isinstance(fact, str) and len(fact) > 3 and "yo'q" not in fact.lower() and "bo'sh" not in fact.lower():
            await db.add_memory(0, fact)
            logger.info(f"Learned new admin fact: {fact}")

    try:
        admin_reply_text = ai_response.get("admin_message", "Tahlil tugadi.")
        draft_text = ai_response.get("draft_text", "")
        schedule_time = ai_response.get("schedule_unix_time")
        autopilot_hours = ai_response.get("autopilot_duration_hours")

        if autopilot_hours and autopilot_hours > 0:
            await db.set_autopilot(target_user_id, autopilot_hours)
            admin_reply_text = f"✅ <b>Avtopilot faollashdi!</b> Kelasi {autopilot_hours} soat davomida u bilan o'zim mustaqil gaplashaman.\n\n" + admin_reply_text

        if draft_text:
            schedule_str = ""
            if schedule_time:
                import datetime
                dt = datetime.datetime.fromtimestamp(schedule_time)
                schedule_str = f"\n🕒 <b>Reja:</b> {dt.strftime('%Y-%m-%d %H:%M')}\n"

            draft_card = (
                f"🤖 <b>Kotiba:</b> {admin_reply_text}\n\n"
                f"📝 <b>Qoralama:</b>\n<blockquote>{draft_text}</blockquote>\n"
                f"{schedule_str}"
                f"👇 <b>Tasdiqlash uchun shu xabarga 'ok' yoki 'yubor' deb javob (reply) yozing.</b>\n"
                f"Bekor qilish uchun 'bekor'."
            )
            draft_msg = await status_msg.edit_text(draft_card, parse_mode=filters.enums.ParseMode.HTML)
            
            # Save draft state
            await db.save_message_draft(admin_msg_id, draft_msg.id, draft_text, schedule_time)
            
        else:
            # Just an admin conversation
            await status_msg.edit_text(f"🤖 <b>Kotiba:</b>\n{admin_reply_text}", parse_mode=filters.enums.ParseMode.HTML)

    except Exception as e:
        logger.error(f"Unexpected error while drafting reply: {e}")
        await status_msg.edit_text(f"❌ <b>Xatolik:</b> {e}", parse_mode=filters.enums.ParseMode.HTML)

async def main():
    """Main application startup procedure."""
    logger.info("Initializing SQLite database...")
    await db.init_db()

    logger.info("Starting Pyrogram Userbot Client...")
    await app.start()
    
    # Inject running Pyrogram client into FastAPI web app & DB memory sync
    set_pyrogram_client(app)
    db.set_db_client(app)

    # Automatically restore memories from Telegram Cloud Backup
    await db.restore_memories_from_telegram(app)

    me = await app.get_me()
    logger.info(f"Userbot started successfully as: {me.first_name} (@{me.username or 'No Username'})")
    logger.info(f"Admin Chat Target: {config.ADMIN_CHAT_ID}")

    # Configure Uvicorn Web Server
    uvicorn_config = uvicorn.Config(
        app=fastapi_app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        log_level="warning"
    )
    server = uvicorn.Server(uvicorn_config)

    logger.info("🌐 Web Dashboard UI active at: http://localhost:8000")

    # Run Pyrogram Client and FastAPI Uvicorn Server concurrently
    await server.serve()

if __name__ == "__main__":
    try:
        app.run(main())
    except KeyboardInterrupt:
        logger.info("Userbot stopped by user.")

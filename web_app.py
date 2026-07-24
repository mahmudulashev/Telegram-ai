import os
import logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Optional, List, Dict, Any
from pydantic import BaseModel

import db
import ai_agent
import learner
import config

logger = logging.getLogger("WebApp")

app = FastAPI(title="Telegram AI Secretary Dashboard")

# Setup templates directory
templates_dir = os.path.join(os.path.dirname(__file__), "templates")
os.makedirs(templates_dir, exist_ok=True)
templates = Jinja2Templates(directory=templates_dir)

# Pyrogram Client reference (injected from main.py)
pyrogram_client = None

def set_pyrogram_client(client):
    global pyrogram_client
    pyrogram_client = client

class WebChatRequest(BaseModel):
    message_id: int
    instruction: str

class SendDraftRequest(BaseModel):
    message_id: int
    draft_text: str

class GeneralChatRequest(BaseModel):
    instruction: str
    chat_history: list = []

class SyncHistoryRequest(BaseModel):
    limit_per_chat: int = 50

class SetAutopilotRequest(BaseModel):
    user_id: int
    expires_at: Optional[int] = None
    hours: Optional[int] = None

async def auto_sync_recent_dialogs(client):
    """Auto-populate recent Telegram dialogs into local DB if feed is empty."""
    if not client:
        return
    try:
        async for dialog in client.get_dialogs(limit=25):
            chat = dialog.chat
            if getattr(chat, 'type', None) and chat.type.value in ["private", "bot"]:
                first_name = getattr(chat, "first_name", "") or ""
                last_name = getattr(chat, "last_name", "") or ""
                username = getattr(chat, "username", "") or ""

                async for msg in client.get_chat_history(chat.id, limit=1):
                    if not msg.text:
                        continue
                    is_outgoing = msg.outgoing or (msg.from_user and getattr(msg.from_user, 'is_self', False))
                    await db.save_historical_message(
                        user_id=chat.id,
                        user_msg_id=msg.id,
                        first_name=first_name,
                        last_name=last_name,
                        username=username,
                        incoming_text=msg.text,
                        category="Casual",
                        summary=msg.text[:100],
                        status="replied" if is_outgoing else "pending"
                    )
    except Exception as e:
        logger.warning(f"Auto-sync dialogs error: {e}")

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    """Render main Web UI Dashboard."""
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/api/stats")
async def get_dashboard_stats():
    """Return system statistics for charts and dashboard cards."""
    stats = await db.get_stats()
    if stats.get("total_messages", 0) == 0 and pyrogram_client:
        await auto_sync_recent_dialogs(pyrogram_client)
        stats = await db.get_stats()

    status_info = {
        "status": "Online",
        "model": config.OPENAI_MODEL,
        "admin_chat": config.ADMIN_CHAT_ID
    }
    return JSONResponse({**stats, "system": status_info})

@app.get("/api/messages")
async def get_dashboard_messages(limit: int = 50):
    """Return message feed for the dashboard."""
    messages = await db.get_all_messages(limit=limit)
    if not messages and pyrogram_client:
        await auto_sync_recent_dialogs(pyrogram_client)
        messages = await db.get_all_messages(limit=limit)
    return JSONResponse({"messages": messages})

@app.get("/api/chat/{message_id}")
async def get_web_chat_history_api(message_id: int):
    """Return chat history between Admin and AI for a specific message."""
    history = await db.get_web_chat_history(message_id)
    return JSONResponse({"history": history})

@app.post("/api/chat")
async def process_web_chat(payload: WebChatRequest):
    """Converse with the AI Agent in the Web UI."""
    if not pyrogram_client:
        raise HTTPException(status_code=500, detail="Telegram Pyrogram client is not running.")

    msg_context = await db.get_message_by_id(payload.message_id)
    if not msg_context:
        raise HTTPException(status_code=404, detail="Message not found.")

    # Save user instruction to Web Chat DB
    await db.add_web_chat_message(payload.message_id, "user", payload.instruction)

    target_user_id = msg_context["user_id"]
    
    # Fetch contexts
    recent_context = ""
    try:
        history = []
        async for msg in pyrogram_client.get_chat_history(target_user_id, limit=25):
            is_me = msg.outgoing or (msg.from_user and getattr(msg.from_user, 'is_self', False))
            sender = "Siz (Mahmud)" if is_me else "Suhbatdosh"
            time_str = msg.date.strftime("%H:%M") if msg.date else ""
            text = msg.text or msg.caption or "[Media]"
            history.append(f"[{time_str}] {sender}: {text}")
        if history:
            history.reverse()
            recent_context = "\n".join(history)
    except Exception as e:
        logger.warning(f"Could not fetch recent history for Web Chat: {e}")

    past_memories = await db.get_memories(target_user_id, limit=10)
    admin_memories_data = await db.get_all_admin_memories()
    admin_memories_texts = [m['fact'] for m in admin_memories_data]
    web_chat_history = await db.get_web_chat_history(payload.message_id)

    # Generate AI Response
    ai_response = await ai_agent.web_chat_response(
        chat_history=web_chat_history,
        context=msg_context,
        recent_context=recent_context,
        past_memories=past_memories,
        admin_memories=admin_memories_texts
    )

    admin_reply_text = ai_response.get("admin_message", "Tahlil tugadi.")
    draft_text = ai_response.get("draft_text", "")
    autopilot_hours = ai_response.get("autopilot_duration_hours")

    if autopilot_hours and autopilot_hours > 0:
        await db.set_autopilot(target_user_id, autopilot_hours)
        admin_reply_text = f"✅ <b>Avtopilot faollashdi!</b> Kelasi {autopilot_hours} soat davomida u bilan o'zim mustaqil gaplashaman.<br><br>" + admin_reply_text

    # Save any new admin facts
    new_admin_facts = ai_response.get("new_admin_facts_to_remember", [])
    for fact in new_admin_facts:
        if isinstance(fact, str) and len(fact) > 3 and "yo'q" not in fact.lower() and "bo'sh" not in fact.lower():
            await db.add_memory(0, fact)
            logger.info(f"Learned new admin fact from web chat: {fact}")

    # Save AI response to DB
    await db.add_web_chat_message(payload.message_id, "assistant", admin_reply_text, draft_text)

    return JSONResponse({
        "success": True,
        "admin_message": admin_reply_text,
        "draft_text": draft_text
    })

@app.get("/api/admin_memories")
async def get_admin_memories():
    """Return all facts the AI learned about the Admin."""
    memories = await db.get_all_admin_memories()
    return JSONResponse({"memories": memories})

@app.delete("/api/admin_memories/{mem_id}")
async def delete_admin_memory(mem_id: int):
    """Delete a specific learned fact."""
    success = await db.delete_memory(mem_id)
    if success:
        return JSONResponse({"success": True})
    raise HTTPException(status_code=500, detail="Failed to delete memory")

@app.post("/api/send_draft")
async def send_web_draft(payload: SendDraftRequest):
    """Send the approved draft to the user via Telegram."""
    if not pyrogram_client:
        raise HTTPException(status_code=500, detail="Telegram Pyrogram client is not running.")

    msg_context = await db.get_message_by_id(payload.message_id)
    if not msg_context:
        raise HTTPException(status_code=404, detail="Message not found.")

    target_user_id = msg_context["user_id"]
    target_msg_id = msg_context["user_msg_id"]
    admin_msg_id = msg_context["admin_msg_id"]

    try:
        # Send message to user via Pyrogram
        await pyrogram_client.send_message(
            chat_id=target_user_id,
            text=payload.draft_text,
            reply_to_message_id=target_msg_id
        )

        # Update DB status
        await db.update_message_response(admin_msg_id, payload.draft_text)

        return JSONResponse({
            "success": True,
            "recipient_id": target_user_id
        })
    except Exception as e:
        logger.error(f"Error sending draft from Web UI: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/general_chat")
async def process_general_chat(payload: GeneralChatRequest):
    """Converse directly with the AI Agent globally (no specific user)."""
    admin_memories_data = await db.get_all_admin_memories()
    admin_memories_texts = [m['fact'] for m in admin_memories_data]

    recent_messages = await db.get_all_messages(limit=10)
    recent_msgs_summary = []
    for m in recent_messages:
        sender = f"{m.get('first_name','') or ''} {m.get('last_name','') or ''}".strip() or m.get('username','') or f"User {m.get('user_id')}"
        recent_msgs_summary.append(f"- [{sender}]: {m.get('incoming_text','')} (Kategoriya: {m.get('category','')}, Holat: {m.get('status','')})")
    recent_msgs_text = "\n".join(recent_msgs_summary) if recent_msgs_summary else "Hozircha bazada yangi kelgan Telegram xabarlari yo'q."

    ai_response = await ai_agent.general_chat_response(
        chat_history=payload.chat_history,
        instruction=payload.instruction,
        admin_memories=admin_memories_texts,
        recent_msgs_text=recent_msgs_text
    )

    ai_reply = ai_response.get("ai_reply", "Tahlil tugadi.")

    # Save any new admin facts
    new_admin_facts = ai_response.get("new_admin_facts_to_remember", [])
    for fact in new_admin_facts:
        if isinstance(fact, str) and len(fact) > 3 and "yo'q" not in fact.lower() and "bo'sh" not in fact.lower():
            await db.add_memory(0, fact)
            logger.info(f"Learned new global rule from general chat: {fact}")

    return JSONResponse({
        "success": True,
        "ai_reply": ai_reply
    })

@app.post("/api/sync_history")
async def sync_telegram_history(payload: SyncHistoryRequest):
    """Sync historical Telegram messages into AI memory & tone-of-voice training without polluting main feed."""
    if not pyrogram_client:
        raise HTTPException(status_code=500, detail="Pyrogram client is not active.")

    try:
        # Run background learning on past history
        result = await learner.sync_and_learn_all(pyrogram_client)
        
        return JSONResponse({
            "success": True,
            "message": f"Sinxronizatsiya yakunlandi! {result['contacts_analyzed']} ta suhbatdosh, {result['my_messages_analyzed']} ta sizning xabaringiz o'rganildi. {result['facts_learned']} ta yangi fakt AI Xotirasiga saqlandi va asboblar paneli tozalandi."
        })
    except Exception as e:
        logger.error(f"Error syncing and learning history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class GlobalAutopilotRequest(BaseModel):
    enabled: bool

@app.get("/api/autopilot/global")
async def get_global_autopilot_status():
    """Check if global autopilot is enabled for all chats."""
    active = await db.is_global_autopilot_active()
    return JSONResponse({"success": True, "global_autopilot": active})

@app.post("/api/autopilot/global")
async def toggle_global_autopilot(payload: GlobalAutopilotRequest):
    """Enable or disable global autopilot for all chats."""
    success = await db.set_global_autopilot(payload.enabled)
    return JSONResponse({"success": success, "global_autopilot": payload.enabled})

@app.get("/api/autopilot")
async def get_autopilots():
    """Retrieve all active autopilot sessions."""
    active = await db.get_active_autopilots()
    return JSONResponse({"success": True, "autopilots": active})

@app.post("/api/autopilot/set")
async def set_autopilot_endpoint(payload: SetAutopilotRequest):
    """Enable or schedule autopilot for a user."""
    if payload.expires_at:
        success = await db.set_autopilot_until(payload.user_id, payload.expires_at)
    elif payload.hours:
        success = await db.set_autopilot(payload.user_id, payload.hours)
    else:
        raise HTTPException(status_code=400, detail="Must provide expires_at timestamp or hours.")
    
    if success:
        return JSONResponse({"success": True})
    raise HTTPException(status_code=500, detail="Failed to set autopilot")

@app.delete("/api/autopilot/{user_id}")
async def disable_autopilot_endpoint(user_id: int):
    """Disable autopilot for a user."""
    success = await db.disable_autopilot(user_id)
    if success:
        return JSONResponse({"success": True})
    raise HTTPException(status_code=500, detail="Failed to disable autopilot")

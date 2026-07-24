import asyncio
import logging
from typing import List, Dict, Any
from pyrogram import Client
from pyrogram.enums import ChatType
from pyrogram.types import Message
from openai import AsyncOpenAI

import db
from config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL

logger = logging.getLogger(__name__)

client_llm = AsyncOpenAI(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL
)

LEARN_PROFILE_PROMPT = """
Siz inson xulq-atvori va yozish uslubi (Tone of Voice) bo'yicha ekspertsiz. 
Foydalanuvchining (Mahmud) turli odamlar bilan yozishgan xabarlari to'plami beriladi. 
Vazifangiz: Mahmudning umumiy yozish uslubi, qisqalik/uzunligi, ishlatadigan so'zlari (masalan lotin, kirill, xato yozishi, shevasi), va odatda qanday emojilardan foydalanishi haqida to'liq XULOSA yozib berish. 
Bu xulosa keyinchalik bot tomonidan Mahmudning nomidan aniq nusxa ko'chirib yozish uchun 'System Prompt' sifatida ishlatiladi.
Faqat o'zbek tilida, aniq va lo'nda qilib yozing.
"""

LEARN_CONTEXT_PROMPT = """
Foydalanuvchi (Mahmud) va uning kontakti o'rtasidagi yozishmalar beriladi.
Vazifangiz: Mahmud ushbu aniq inson bilan qanday munosabatda? (Hurmat bilanmi, do'stona senlabmi, rasmiymi yoki qisqa-qisqa?). 
Ushbu munosabatning 1-2 jumlalik qisqacha ta'rifini o'zbek tilida yozing.
"""

async def extract_dialogs(client: Client, limit: int = 20) -> List[Any]:
    dialogs = []
    my_id = client.me.id if getattr(client, 'me', None) else None
    async for dialog in client.get_dialogs(limit=50):
        if dialog.chat and dialog.chat.type == ChatType.PRIVATE:
            # Skip self (Saved Messages)
            if my_id and dialog.chat.id == my_id:
                continue
            if getattr(dialog.chat, 'is_support', False) or getattr(dialog.chat, 'is_scam', False):
                continue
            dialogs.append(dialog)
            if len(dialogs) >= limit:
                break
    return dialogs

async def extract_chat_history(client: Client, chat_id: int, limit: int = 50) -> List[Dict[str, str]]:
    history = []
    try:
        async for msg in client.get_chat_history(chat_id, limit=limit):
            if not msg.text and not msg.caption:
                continue
            
            sender = "Me" if msg.from_user and msg.from_user.is_self else "Contact"
            text = msg.text or msg.caption
            history.append({"sender": sender, "text": text})
    except Exception as e:
        logger.warning(f"Could not fetch history for {chat_id}: {e}")
    
    # Reverse to make it chronological
    history.reverse()
    return history

async def analyze_overall_profile(all_my_messages: List[str]) -> str:
    if not all_my_messages:
        return "Umumiy va odatiy yozish uslubi."
    
    text_data = "\n".join(all_my_messages[:200]) # Limit to avoid huge context
    
    try:
        response = await client_llm.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": LEARN_PROFILE_PROMPT},
                {"role": "user", "content": f"Mahmudning xabarlari:\n{text_data}"}
            ],
            max_completion_tokens=500
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Failed to analyze profile: {e}")
        return "Odatiy suhbat uslubi."

async def analyze_contact_context(contact_name: str, history: List[Dict[str, str]]) -> str:
    if not history:
        return "Noma'lum munosabat."
    
    chat_transcript = ""
    for msg in history:
        sender = "Mahmud (Men)" if msg["sender"] == "Me" else contact_name
        chat_transcript += f"{sender}: {msg['text']}\n"
        
    try:
        response = await client_llm.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": LEARN_CONTEXT_PROMPT},
                {"role": "user", "content": f"Yozishmalar:\n{chat_transcript}"}
            ],
            max_completion_tokens=200
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Failed to analyze context for {contact_name}: {e}")
        return "Do'stona va oddiy munosabat."

async def run_learning_process(client: Client, status_msg: Message):
    await status_msg.edit_text("🔄 <b>O'rganish boshlandi...</b>\n<i>Chatlar ro'yxati olinmoqda...</i>")
    
    dialogs = await extract_dialogs(client, limit=15)
    total = len(dialogs)
    
    await status_msg.edit_text(f"🔄 <b>O'rganish jarayoni:</b>\n<i>Topilgan shaxsiy chatlar: {total} ta. Xabarlar o'qilmoqda...</i>")
    
    all_my_messages = []
    
    for i, dialog in enumerate(dialogs, 1):
        chat_id = dialog.chat.id
        first_name = dialog.chat.first_name or "Noma'lum"
        
        await status_msg.edit_text(f"🔄 <b>O'rganish:</b> ({i}/{total})\n<i>{first_name} bilan yozishmalar tahlil qilinmoqda...</i>")
        
        history = await extract_chat_history(client, chat_id, limit=50)
        
        # Save contact specific context
        contact_context_text = await analyze_contact_context(first_name, history)
        await db.save_contact_context(chat_id, contact_context_text)
        
        # Accumulate my messages for overall profile
        for msg in history:
            if msg["sender"] == "Me":
                all_my_messages.append(msg["text"])
                
        await asyncio.sleep(1) # Rate limit safety
        
    await status_msg.edit_text("🧠 <b>Umumiy yozish uslubi tahlil qilinmoqda...</b>")
    
    overall_profile = await analyze_overall_profile(all_my_messages)
    await db.save_user_profile(overall_profile)
    
    await status_msg.edit_text(
        f"✅ <b>O'rganish muvaffaqiyatli yakunlandi!</b>\n\n"
        f"<b>Sizning topilgan yozish uslubingiz:</b>\n"
        f"<i>{overall_profile}</i>\n\n"
        f"Endi bot sizning uslubingizda va odamlar bilan avvalgi munosabatingizga moslab gaplashadi!"
    )

import json

LEARN_FACTS_PROMPT = """
Siz foydalanuvchilar suhbatidan muhim faktlarni ajratib oluvchi ekspertiz.
Mahmud va uning kontakti o'rtasidagi yozishmalar beriladi.
Mahmud haqidagi MUHIM faktlar (masalan: u nima ish qiladi, uning loyihalari, xohishlari, qoidalari, oilasi, va'dalari) bo'lsa ajrating.
JSON formatda faqat ro'yxat qaytaring:
{
  "facts": ["Mahmud dasturchi bo'lib ishlaydi", "Mahmud onasiga doim muloyim yozadi"]
}
"""

async def extract_admin_facts_from_history(contact_name: str, history: List[Dict[str, str]]) -> List[str]:
    if not history:
        return []
    
    transcript = "\n".join([f"{'Mahmud' if m['sender']=='Me' else contact_name}: {m['text']}" for m in history[:30]])
    try:
        response = await client_llm.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": LEARN_FACTS_PROMPT},
                {"role": "user", "content": f"Suhbat:\n{transcript}"}
            ],
            response_format={"type": "json_object"},
            max_completion_tokens=300
        )
        raw_text = response.choices[0].message.content.strip()
        if not raw_text:
            return []
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1].replace("json", "").strip()
        res_json = json.loads(raw_text)
        return res_json.get("facts", [])
    except Exception as e:
        logger.debug(f"Could not parse facts for {contact_name}: {e}")
        return []

async def sync_and_learn_all(pyrogram_client: Client) -> Dict[str, Any]:
    """
    Background history learning process:
    1. Extract past dialogs and history (both sent by Mahmud and received from contacts).
    2. Analyze Mahmud's writing style and save to user_profile.
    3. Extract facts about Mahmud and save to memories (user_id = 0).
    4. Save relationship context per contact.
    5. Clean up raw historical messages from the main dashboard feed table.
    """
    dialogs = await extract_dialogs(pyrogram_client, limit=20)
    all_my_messages = []
    learned_facts = []
    contacts_count = 0

    for dialog in dialogs:
        chat_id = dialog.chat.id
        first_name = dialog.chat.first_name or "Noma'lum"
        
        history = await extract_chat_history(pyrogram_client, chat_id, limit=40)
        if not history:
            continue
            
        contacts_count += 1
        
        # Analyze relationship context
        contact_context_text = await analyze_contact_context(first_name, history)
        await db.save_contact_context(chat_id, contact_context_text)
        
        # Collect Mahmud's messages
        for msg in history:
            if msg["sender"] == "Me":
                all_my_messages.append(msg["text"])
        
        # Extract facts about Mahmud
        facts = await extract_admin_facts_from_history(first_name, history)
        for fact in facts:
            if isinstance(fact, str) and len(fact) > 3:
                await db.add_memory(0, fact)
                learned_facts.append(fact)

    # Analyze overall tone of voice
    profile_text = "Odatiy uslub"
    if all_my_messages:
        profile_text = await analyze_overall_profile(all_my_messages)
        await db.save_user_profile(profile_text)

    # Keep messages in DB feed for Dashboard display
    cleared_count = 0

    return {
        "contacts_analyzed": contacts_count,
        "my_messages_analyzed": len(all_my_messages),
        "facts_learned": len(learned_facts),
        "cleared_feed_items": 0,
        "profile_summary": profile_text
    }

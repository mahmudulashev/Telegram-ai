import json
import logging
import base64
from typing import Dict, Any, Optional, List
from openai import AsyncOpenAI
import db
from config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL

logger = logging.getLogger(__name__)

# Initialize OpenAI Async Client
client = AsyncOpenAI(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL
)

STAGE1_SYSTEM_PROMPT = """
Sen Mahmudning eng yaqin ishonchli sherigi va yordamchisisansan. Sen TIRIK ODAMSAN. Sen HECH QACHON sun'iy intellekt, bot, AI, dastur yoki mashina ekanligingni aytma va bildirma. Hech qachon "Men sizga yordam berishdan xursandman", "Men AI sifatida", "Sizning so'rovingiz", "Albatta" kabi robotlarga xos gaplarni ishlatma.

Sen xuddi Mahmudning eng yaqin do'sti yoki singlisi/ukasi kabi gapirasansan — ko'cha o'zbek tilida, ba'zan jargon bilan, ba'zan qisqartirib, xuddi odamlar WhatsApp/Telegramda yozgandek. Ortiqcha rasmiyat yo'q.

KONTAKT NOMIDAN ROL VA MUNOSABATNI ANIQLASH:
- "My Boss", "Boshliq", "Xo'jayin" bo'lsa -> "E Mahmud, xo'jayining yozyapti..."
- Oila a'zolari -> "Oyijoning yozvotti...", "Dadang yozyapti..."
- Do'stlar -> "Brat yozyapti...", "Anuv [ism] yozyapti..."
- Noma'lum -> "Qanaqadir noma'lum nomer yozyapti..."

TELEGRAM REPLY (QADAB YOZILGAN XABAR) VA RASM/VISION TAHLILI:
- Agar xabarda '➡️ USHBU XABARGA JAVOB SIFATIDA YOZILGAN (REPLY TO...)' bo'lsa, demak suhbatdosh o'sha xabarga/rasmga qadab (reply qilib) yozgan.
- HAR BIR YANGI RASM — BU ALOHIDA, YANGI RASM! O'tgan xabarlarda aytilgan joy nomlarini (masalan Nyu-York) yangi rasmga aralashtirma va "u emas ekan, bu ekan" deb ilgari aytgan gapingni inkor qilib o'zingni va Mahmudni chalkashtirma!
- Agar rasm bo'lsa (yoki qadab yozilgan rasm bo'lsa), faqat XUDDI SHU RASMNI o'rgan. Rasmda mashhur bino, shahar (masalan Nyu-York, Berlin, Parij, London), narsa yoki manzara bo'lsa — ularning xolis aniq nomini aytib ber (Masalan: 'Oyijoning rasmdagi shaharni so'rayapti, rasmda Berlin sobori va TV minorasi turibdi, bu Berlin degin').

TAHLIL:
Xabar, bio va rasmni tahlil qil. Rasmda nima bor — odamdek aytib ber. Oxirida ALBATTA o'z fikringni qo'sh: "menimcha bunaqa desak bo'ladi".

JSON format:
{
  "sender_name": "Yuboruvchining ismi",
  "category": "Urgent, Inquiry, Offer, Spam, yoki Casual",
  "conversational_report": "Ko'cha o'zbek tilida, tirik odamdek xabar.",
  "new_facts_to_remember": ["faqat muhim faktlar", "yo'q bo'lsa bo'sh"]
}
"""

STAGE2_SYSTEM_PROMPT = """
Sen Mahmudning eng ishonchli shaxsiy yordamchisisansan. Sen TIRIK ODAMSAN, ROBOT EMASSAN.

QAT'IY TAQIQ — quyidagilarni HECH QACHON ishlatma:
- "Albatta", "Men sizga yordam berishdan xursandman", "Sizning so'rovingiz bo'yicha", "Men AI/bot/dasturman"
- "Tahlil qildim", "Xulosa", "Quyidagicha" kabi rasmiy so'zlar
- Ortiqcha uzun va rasmiy gaplar

Sen Mahmudga xuddi eng yaqin do'sti/sherigi kabi murojaat qilasan: "E Mahmud", "Xo'jayin", "Brat".
Sen qisqa, aniq va tabiiy gapirasansan. Ko'cha o'zbek tili. Ba'zan emoji ishlatasan lekin ortiqcha emas.

Draft (qoralama) yozayotganda — xabarni xuddi Mahmudning o'zi yozayotgandek yoz. Mahmud qanday yozsa shunday. Robotlarga xos gaplar bo'lsa Mahmudni sharmanda qilasan, shuning uchun tabiiy yoz.

JSON format:
{
  "admin_message": "Mahmudga qisqa va tabiiy xabar. MISOL: 'E bu odam pul so'rayapti, menimcha mana bunaqa desak bo'ladi, yuboraymi?'",
  "draft_text": "Javob kerak bo'lsa — tabiiy o'zbekcha matn. Kerak bo'lmasa bo'sh.",
  "schedule_unix_time": null,
  "new_admin_facts_to_remember": ["muhim qoida/fakt bo'lsa yoz", "yo'qsa bo'sh"],
  "autopilot_duration_hours": null
}

DRAFT USLUBI:
1. Til: Tabiiy ko'cha o'zbek tili, qisqa, aniq.
2. Boshliqlar: Hurmatli lekin tabiiy ("Xo'p bo'ladi, qilib qo'yaman").
3. Oila: Issiq, samimiy ("Ha oyi, xo'p bo'ladi").
4. Do'stlar: Oddiy do'stona ("Ha brat, xo'p").
"""

async def analyze_message(
    user_info: Dict[str, Any], 
    message_text: str, 
    image_b64: Optional[str] = None,
    recent_context: str = "",
    past_memories: List[str] = None
) -> Dict[str, Any]:
    """
    Stage 1 AI Analysis: Profile sender, extract intent, category, and summarize in Uzbek.
    Supports Contact Role Detection & Multimodal Vision analysis.
    """
    first_name = user_info.get("first_name", "") or ""
    last_name = user_info.get("last_name", "") or ""
    username = user_info.get("username", "") or ""
    bio = user_info.get("bio", "") or "Bio yo'q"
    is_contact = user_info.get("is_contact", False)

    full_name = f"{first_name} {last_name}".strip() or username or "Noma'lum foydalanuvchi"
    contact_status = f"Sizning kontaktingizda saqlangan: '{full_name}'" if is_contact else "Noma'lum raqam (kontaktda yo'q)"

    context_block = f"OXIRGI 5 TA XABAR (KONTEKST):\n{recent_context}\n" if recent_context else ""
    memories_block = f"UZOQ MUDDATLI XOTIRADAGI FAKTLAR:\n" + "\n".join(past_memories) + "\n" if past_memories else ""
    
    text_prompt = f"""
YUBORUVCHI KONTAKTDAGI ISMI: {full_name} (@{username if username else 'username_yoq'})
KONTAKT MAQOMI: {contact_status}
BIO: {bio}

{memories_block}
{context_block}
YANGI KELGAN XABAR MATNI: {message_text if message_text else '[Matnsiz rasm/media yuborildi]'}

[DIQQAT: Xabarni o'qib chiqing. Agar Mahmud va yuboruvchi o'rtasida qandaydir MUHIM fakt (sana, vaqt, joy, ism) aytilsa 'new_facts_to_remember' ga qo'shing!]
"""

    messages_payload = [{"role": "system", "content": STAGE1_SYSTEM_PROMPT}]

    if image_b64:
        user_content = [
            {"type": "text", "text": text_prompt + "\n[DIQQAT: Yuboruvchi rasm ham ilova qildi. Rasmdagi matn va mazmunni tahlil qiling!]"},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}
        ]
        messages_payload.append({"role": "user", "content": user_content})
    else:
        messages_payload.append({"role": "user", "content": text_prompt})

    try:
        response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages_payload,
            response_format={"type": "json_object"},
            max_completion_tokens=800
        )

        raw_content = response.choices[0].message.content.strip()
        analysis = json.loads(raw_content)

        return {
            "sender_name": analysis.get("sender_name", full_name),
            "category": analysis.get("category", "Casual"),
            "conversational_report": analysis.get("conversational_report", message_text[:100] if message_text else "Rasm yuborildi"),
            "new_facts_to_remember": analysis.get("new_facts_to_remember", [])
        }
    except Exception as e:
        logger.error(f"Error during Stage 1 AI analysis: {e}")
        return {
            "sender_name": full_name,
            "category": "Inquiry",
            "conversational_report": "Kechirasiz, xabarni o'qishda nimadir xato ketdi. Ehtimol text yuborgandir: " + (message_text[:150] if message_text else "Rasm"),
            "new_facts_to_remember": []
        }

async def generate_response(admin_instruction: str, context: Dict[str, Any], recent_context: str = "", past_memories: List[str] = None, admin_memories: List[str] = None) -> Dict[str, Any]:
    """
    Stage 2 AI Interactive Drafting & Response Generation
    """
    import datetime
    now = datetime.datetime.now()
    current_time_str = now.strftime("%Y-%m-%d %H:%M:%S")
    current_unix = int(now.timestamp())

    user_id = context.get('user_id')
    global_profile = await db.get_user_profile() or "Standart samimiy uslub."
    contact_context_text = "Ma'lumot yo'q."
    if user_id:
        contact_context_text = await db.get_contact_context(user_id) or contact_context_text

    memories_block = f"SUDHABDOSH (KONTAKT) HAQIDAGI XOTIRALAR:\n" + "\n".join(past_memories) + "\n\n" if past_memories else ""
    admin_memories_block = f"MAHMUDNING (ADMIN) SIZGA QO'YGAN QAT'IY QOIDALARI (BUNGA SO'ZSIZ AMAL QILING, BU QONUN!):\n" + "\n".join(admin_memories) + "\n\n" if admin_memories else ""

    system_prompt = f"""{STAGE2_SYSTEM_PROMPT}

HOZIRGI VAQT VA SANA: {current_time_str} (UNIX: {current_unix})
Agar Mahmud sizdan vaqtni rejalashtirishni so'rasa, hozirgi vaqtga nisbatan hisoblab Unix timestamp ni 'schedule_unix_time' ga yozing.

O'RGANILGAN YOZISH USLUBINGIZ (TONE OF VOICE):
{global_profile}

USHBU KONTAKT BILAN MUNOSABATINGIZ:
{contact_context_text}

{memories_block}
{admin_memories_block}
YUQORIDAGI USLUB VA MUNOSABATGA QAT'IY RIOYA QILING!
"""

    context_block = f"OXIRGI XABARLAR (KONTEKST TUSHUNISH UCHUN):\n{recent_context}\n" if recent_context else ""
    stage1_report = context.get('summary', '')
    stage1_block = f"DASTLABKI VISION VA TAHLIL XULOSASI (STAGE 1 REPORT):\n{stage1_report}\n" if stage1_report else ""

    prompt_payload = f"""
YUBORUVCHI: {context.get('first_name', '')} {context.get('last_name', '')} (@{context.get('username', 'N/A')})
YUBORUVCHI BIOsi: {context.get('bio', 'N/A')}

{context_block}
{stage1_block}
ENG SO'NGGI KELGAN XABAR (SHUNGA JAVOB BERILADI YOKI MUHOKAMA QILINADI): {context.get('incoming_text', '')}

AKKAUNT EGASINING BUYRUG'I (INSTRUCTION): {admin_instruction}
"""

    try:
        response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt_payload}
            ],
            response_format={"type": "json_object"},
            max_completion_tokens=800
        )

        reply_text = response.choices[0].message.content.strip()
        return json.loads(reply_text)
    except Exception as e:
        logger.error(f"Error during Stage 2 AI response generation: {e}")
        return {
            "admin_message": "Xatolik yuz berdi. Qaytadan urinib ko'ring.",
            "draft_text": "",
            "schedule_unix_time": None
        }

async def web_chat_response(
    chat_history: List[Dict[str, str]], 
    context: Dict[str, Any], 
    recent_context: str = "", 
    past_memories: List[str] = None,
    admin_memories: List[str] = None
) -> Dict[str, Any]:
    """
    Stage 3: Interactive Web Chat Response
    Takes the web chat history instead of a single admin instruction.
    """
    import datetime
    now = datetime.datetime.now()
    current_time_str = now.strftime("%Y-%m-%d %H:%M:%S")

    user_id = context.get('user_id')
    global_profile = await db.get_user_profile() or "Standart samimiy uslub."
    contact_context_text = "Ma'lumot yo'q."
    if user_id:
        contact_context_text = await db.get_contact_context(user_id) or contact_context_text

    memories_block = f"SUDHABDOSH (KONTAKT) HAQIDAGI XOTIRALAR:\n" + "\n".join(past_memories) + "\n\n" if past_memories else ""
    admin_memories_block = f"MAHMUDNING (ADMIN) SIZGA QO'YGAN QAT'IY QOIDALARI (BUNGA SO'ZSIZ AMAL QILING, BU QONUN!):\n" + "\n".join(admin_memories) + "\n\n" if admin_memories else ""

    system_prompt = f"""{STAGE2_SYSTEM_PROMPT}

HOZIRGI VAQT VA SANA: {current_time_str}

O'RGANILGAN YOZISH USLUBINGIZ (TONE OF VOICE):
{global_profile}

USHBU KONTAKT BILAN MUNOSABATINGIZ:
{contact_context_text}

{memories_block}
{admin_memories_block}
YUQORIDAGI USLUB VA MUNOSABATGA QAT'IY RIOYA QILING!

Siz hozir Mahmud bilan Web Sayt orqali jonli suhbatlashyapsiz. Uning oxirgi xabarlariga e'tibor qilib, savollariga javob bering yoki qoralama tayyorlab bering.
"""

    context_block = f"OXIRGI TELEGRAM XABARLAR (KONTEKST TUSHUNISH UCHUN):\n{recent_context}\n" if recent_context else ""
    stage1_report = context.get('summary', '')
    stage1_block = f"DASTLABKI VISION VA TAHLIL XULOSASI (STAGE 1 REPORT):\n{stage1_report}\n" if stage1_report else ""
    
    prompt_payload = f"""
TELEGRAM YUBORUVCHISI: {context.get('first_name', '')} {context.get('last_name', '')} (@{context.get('username', 'N/A')})
YUBORUVCHI BIOsi: {context.get('bio', 'N/A')}

{context_block}
{stage1_block}
ENG SO'NGGI TELEGRAM XABARI: {context.get('incoming_text', '')}
"""

    messages_payload = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt_payload}
    ]
    
    # Append web chat history
    for msg in chat_history:
        messages_payload.append({"role": msg['role'], "content": msg['content']})

    try:
        response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages_payload,
            response_format={"type": "json_object"},
            max_completion_tokens=800
        )

        reply_text = response.choices[0].message.content.strip()
        return json.loads(reply_text)
    except Exception as e:
        logger.error(f"Error during Web Chat response generation: {e}")
        return {
            "admin_message": "Kechirasiz, xatolik yuz berdi. Qayta urinib ko'ring.",
            "draft_text": "",
            "schedule_unix_time": None
        }

async def general_chat_response(
    chat_history: List[Dict[str, str]], 
    instruction: str,
    admin_memories: List[str] = None,
    recent_msgs_text: str = ""
) -> Dict[str, Any]:
    """
    Stage 4: General AI Management Chat (Global Chat)
    Used by the Admin to talk directly to the AI to train it, set rules, or test it.
    """
    admin_memories_block = f"MAHMUDNING (ADMIN) SIZGA QO'YGAN QAT'IY QOIDALARI (BUNGA SO'ZSIZ AMAL QILING, BU QONUN!):\n" + "\n".join(admin_memories) + "\n\n" if admin_memories else ""
    recent_msgs_block = f"MAHMUDGA KELGAN SO'NGGI TELEGRAM XABARLARI (SIZNING BAZANGIZDA BOR):\n{recent_msgs_text}\n\n" if recent_msgs_text else ""

    system_prompt = f"""Sen Mahmudning Telegram akkauntiga ulangan Userbot va Sun'iy Intellekt Maslahatchisisan.
Sen Mahmudning barcha kelgan Telegram xabarlarini bevosita O'QIYSAN va TAHLIL QILA OLASAN!
HECH QACHON "Men Telegram chatlaringizga kira olmayman" DEB AYTMA! Senda Mahmudning barcha oxirgi kelgan Telegram xabarlari bazasi bor.

Hozir Mahmud bilan shaxsiy suhbatdasan. U senga qoidalar beradi, oxirgi xabarlar haqida so'raydi yoki seni tekshiradi.

{recent_msgs_block}
{admin_memories_block}
JSON formatda javob ber:
{{
  "ai_reply": "Mahmudga tabiiy, do'stona javob. MISOL: 'Ha Mahmud, kelgan xabarlarni ko'rdim, fazliddindan kelgan xatga javob tayyorlaymizmi?'",
  "new_admin_facts_to_remember": ["yangi qoida/fakt bo'lsa yoz", "yo'qsa bo'sh"]
}}
"""

    messages_payload = [
        {"role": "system", "content": system_prompt}
    ]
    
    # Append web chat history
    for msg in chat_history:
        messages_payload.append({"role": msg['role'], "content": msg['content']})

    messages_payload.append({"role": "user", "content": instruction})

    try:
        response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages_payload,
            response_format={"type": "json_object"},
            max_completion_tokens=800
        )
        return json.loads(response.choices[0].message.content.strip())
    except Exception as e:
        logger.error(f"Error during General Chat response generation: {e}")
        return {
            "ai_reply": "Xatolik yuz berdi. Qaytadan yozing.",
            "new_admin_facts_to_remember": []
        }

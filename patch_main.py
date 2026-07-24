import re

with open('main.py', 'r') as f:
    content = f.read()

# Add _autopilot_tasks at the top level
if "_autopilot_tasks = {}" not in content:
    content = content.replace("app = Client(", "_autopilot_tasks = {}\n\napp = Client(")

# We need to replace the autopilot block inside handle_incoming_private_message
# Find the start of the block:
start_marker = "    if is_autopilot:\n"
end_marker = "            return # Skip manual flow\n"

start_idx = content.find(start_marker)
end_idx = content.find(end_marker, start_idx) + len(end_marker)

old_block = content[start_idx:end_idx]

new_block = """    if is_autopilot:
        # Check rate limit first
        if await db.is_autopilot_rate_limited(user.id, max_per_hour=7):
            logger.info(f"Autopilot 1-hour limit (7 msgs/hour) reached for user {user.id}. Ignoring.")
            return

        # Cancel existing task for this user if any
        if user.id in _autopilot_tasks:
            _autopilot_tasks[user.id].cancel()
            
        async def delayed_autopilot_task(c_user_id, c_message_id, c_display_msg, c_incoming_text, c_user_info, c_image_b64, c_bio, c_first_name, c_last_name, c_username):
            try:
                await asyncio.sleep(90)
            except asyncio.CancelledError:
                return # Cancelled by a newer message

            try:
                recent_context = ""
                history = []
                # Fetch recent context (which will include ALL messages sent during the 90s wait)
                async for msg in client.get_chat_history(c_user_id, limit=25):
                    is_me = msg.outgoing or (msg.from_user and getattr(msg.from_user, 'is_self', False))
                    sender = "Siz (Mahmud)" if is_me else "Suhbatdosh"
                    time_str = msg.date.strftime("%H:%M") if msg.date else ""
                    text = msg.text or msg.caption or "[Media]"
                    history.append(f"[{time_str}] {sender}: {text}")
                
                if history:
                    history.reverse()
                    recent_context = "\\n".join(history)

                past_memories = await db.get_memories(c_user_id, limit=10)
                
                analysis = await ai_agent.analyze_message(
                    user_info=c_user_info, 
                    message_text=c_incoming_text, 
                    image_b64=c_image_b64,
                    recent_context=recent_context,
                    past_memories=past_memories
                )

                category = analysis.get("category", "Casual")
                report = analysis.get('conversational_report', c_incoming_text)

                if category == "Urgent":
                    await db.disable_autopilot(c_user_id)
                    if config.ENABLE_TELEGRAM_NOTIFICATIONS:
                        try:
                            await client.send_message(
                                chat_id=config.ADMIN_CHAT_ID,
                                text=f"🚨 <b>AVTOPILOT TO'XTATILDI: SHOSHILINCH XABAR!</b>\\n<i>Foydalanuvchi '{c_first_name or ''}' dan shoshilinch (Urgent) xabar kelgani uchun avtopilot bu odam uchun darhol o'chirildi!</i>",
                                parse_mode=filters.enums.ParseMode.HTML
                            )
                        except Exception as e:
                            logger.error(f"Urgent override notification failed: {e}")
                    return

                dummy_admin_msg_id = -(c_message_id)
                await db.save_incoming_message(
                    admin_msg_id=dummy_admin_msg_id,
                    user_id=c_user_id,
                    user_msg_id=c_message_id,
                    first_name=c_first_name,
                    last_name=c_last_name,
                    username=c_username,
                    bio=c_bio,
                    incoming_text=c_display_msg,
                    category=category,
                    summary=report
                )
                
                msg_context = await db.get_message_by_admin_msg_id(dummy_admin_msg_id)
                admin_memories = await db.get_all_admin_memories()
                admin_memories_texts = [m['fact'] for m in admin_memories]
                
                # Fetch mimicry style rules
                style_rules = await db.get_style_rules()
                style_rules_texts = [r['rule'] for r in style_rules]

                ai_response = await ai_agent.generate_response(
                    admin_instruction="Siz hozir AVTOPILOT rejimidasiz. Mahmud hozir band. Suhbatdosh bilan mantiqan to'g'ri, qoidalar va xotiralarga tayangan holda mustaqil javob yozib yuboring.",
                    context=msg_context,
                    recent_context=recent_context,
                    past_memories=past_memories,
                    admin_memories=admin_memories_texts,
                    style_rules=style_rules_texts
                )
                
                draft_text = ai_response.get("draft_text", "")
                if draft_text:
                    try:
                        await client.read_chat_history(c_user_id)
                    except Exception as e:
                        logger.debug(f"Could not mark history read: {e}")

                    await client.send_message(chat_id=c_user_id, text=draft_text)
                    await db.update_message_response(dummy_admin_msg_id, draft_text)
                    await db.log_autopilot_response(c_user_id)
                    logger.info(f"Autopilot sent response to {c_user_id}")
            except Exception as e:
                logger.error(f"Error in autopilot task: {e}")
            finally:
                if c_user_id in _autopilot_tasks:
                    del _autopilot_tasks[c_user_id]

        _autopilot_tasks[user.id] = asyncio.create_task(
            delayed_autopilot_task(
                user.id, message.id, display_msg, incoming_text, user_info, image_b64, bio, user.first_name, user.last_name, user.username
            )
        )
        return # Skip manual flow
"""

content = content[:start_idx] + new_block + content[end_idx:]

with open('main.py', 'w') as f:
    f.write(content)
print("main.py patched successfully")

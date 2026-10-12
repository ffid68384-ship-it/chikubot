async def cmd_cancel(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global LAST_PIN
    await del_m(u)
    if not await is_admin(u, c):
        return
    did = CURR_DEAL or f"DL-CHIKU-{DEAL_CTR}"
    if did in DEALS_DB:
        DEALS_DB[did]["status"] = "CANCELLED"
    if LAST_PIN:
        try:
            await c.bot.unpin_chat_message(chat_id=u.effective_chat.id, message_id=LAST_PIN)
        except:
            pass
    user_mention = u.effective_user.mention_html() if u.effective_user else "@Admin"
    msg_text = f"❌ <b>DEAL CANCELLED</b>\n🪪 <b>ID:</b> {did}\n👤 <b>By:</b> {user_mention}"
    sm = await c.bot.send_message(chat_id=u.effective_chat.id, text=msg_text, parse_mode="HTML")
    await safe_pin(c, u.effective_chat.id, sm.message_id)
    LAST_PIN = sm.message_id
    

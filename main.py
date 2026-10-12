async def cmd_cancel(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global LAST_PIN
    await del_m(u)
    if not await is_admin(u, c):
        return
    did = CURR_DEAL or "DL-CHIKU-11254"
    if did in DEALS_DB:
        DEALS_DB[did]["status"] = "CANCELLED"
    if LAST_PIN:
        try:
            await c.bot.unpin_chat_message(chat_id=u.effective_chat.id, message_id=LAST_PIN)
        except:
            pass
    
    user_name = u.effective_user.first_name if u.effective_user else "Admin"
    text = "DEAL CANCELLED\nID: " + did + "\nBy: " + user_name
    sm = await c.bot.send_message(chat_id=u.effective_chat.id, text=text)
    await safe_pin(c, u.effective_chat.id, sm.message_id)
    LAST_PIN = sm.message_id
    

import os, re, unicodedata, threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

web_app = Flask(__name__)
@web_app.route('/')
def home():
    return "Chiku Escrow 24/7"

def run_web():
    web_app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8938665546:AAH-1KMv8sD33fEXGPGYWmLkA9ZYIxfKJ8I")
OWNER_ID = 7364435907
DEALS_DB, STATS = {}, {"deals": 0, "vol": 0.0, "fees": 0.0}
DEAL_CTR, CURR_DEAL, LAST_PIN = 1, None, None

async def is_admin(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if u.effective_user.id == OWNER_ID:
        return True
    try:
        admins = await c.bot.get_chat_administrators(u.effective_chat.id)
        return any(a.user.id == u.effective_user.id for a in admins)
    except:
        return False

def clean_txt(t):
    if not t:
        return ""
    mapping = {
        'ꜱ':'s','s':'s','ᴇ':'e','e':'e','ʟ':'l','l':'l','ʀ':'r','r':'r',
        'ʙ':'b','b':'b','ᴜ':'u','u':'u','ʏ':'y','y':'y','ᴅ':'d','d':'d',
        'ᴀ':'a','a':'a','ᴛ':'t','t':'t','ɪ':'i','i':'i','ᴏ':'o','o':'o',
        'ᴡ':'w','w':'w','м':'m','m':'m','ɴ':'n','n':'n','ᴄ':'c','c':'c',
        'ʜ':'h','h':'h','ᴋ':'k','k':'k','ᴘ':'p','p':'p','ғ':'f','f':'f',
        '𝖴':'u','U':'u','O':'o','О':'o'
    }
    t_norm = unicodedata.normalize('NFKD', str(t))
    res = "".join(mapping.get(ch, ch) for ch in t_norm)
    return res.lower()

def calc_fee(amt):
    if amt <= 0:
        return 0.0, "0%", "0₹", 0.0
    if amt <= 190:
        return 10.0, "Flat ₹10", "Rs 10", amt - 10.0
    if amt <= 599:
        return 20.0, "Flat ₹20", "Rs 20", amt - 20.0
    if amt <= 2000:
        f = round(amt * 0.035, 2)
        return f, "3.5%", f"3.5% - {round(f)}₹", amt - f
    f = round(amt * 0.03, 2)
    return f, "3%", f"3% - {round(f)}₹", amt - f

def get_amt(val):
    if not val:
        return 0.0
    # Usernames aur IDs ko pehle hi hata do taaki @nexatrader78 ka 78 na pakde
    s = re.sub(r"@\w+", "", str(val))
    s = s.lower().replace("₹", "").replace(",", "").replace("rs", "").replace("inr", "")
    m = re.search(r"(\d+(?:\.\d+)?)(\s*k)?", s)
    if m:
        return float(m.group(1)) * (1000 if m.group(2) else 1)
    return 0.0

def parse_form(raw):
    data = {"seller": "", "buyer": "", "details": "", "amount": "", "till": "", "id": ""}
    norm_full = clean_txt(raw)

    dm = re.search(r"dl[-_ ]*chiku[-_ ]*\d+", norm_full)
    if dm:
        data["id"] = re.sub(r"\s+", "", dm.group(0).upper().replace("_", "-"))

    lines = raw.split("\n")
    for line in lines:
        c_line = clean_txt(line).strip()
        if not c_line:
            continue

        parts = re.split(r"[:\-]", line, 1)
        val = parts[1].strip() if len(parts) > 1 else ""

        if "seller" in c_line and not data["seller"]:
            data["seller"] = val
        elif "buyer" in c_line and not data["buyer"]:
            data["buyer"] = val
        elif any(k in c_line for k in ["details", "deatails", "detail"]) and not data["details"]:
            data["details"] = val
        # Check specifically for AMOUNT line
        elif ("am" in c_line and "nt" in c_line) or "amt" in c_line or "price" in c_line:
            if not data["amount"]:
                # Is line me se directly number extract karo
                num_match = re.search(r"(\d+)", val or line)
                if num_match:
                    data["amount"] = num_match.group(1)
                else:
                    data["amount"] = val
        elif "till" in c_line and not data["till"]:
            data["till"] = val

    return data

async def resolve_user(u, rep, ctx, cid):
    if not u or u.upper() == "N/A":
        return u or "N/A"
    clean = u.strip()
    if "(" in clean and ")" in clean:
        return clean
    if clean.isdigit():
        return f'<a href="tg://user?id={clean}">{clean}</a> ({clean})'
    if clean.lower() in ["me", "i", "myself", "mai"] and rep and rep.from_user:
        fu = rep.from_user
        tag = f"@{fu.username}" if fu.username else fu.first_name
        return f"{tag} ({fu.id})"
    if rep and rep.entities:
        for ent in rep.entities:
            if ent.type == "text_mention" and ent.user:
                return f'{ent.user.mention_html()} ({ent.user.id})'
    if clean.startswith("@"):
        try:
            m = await ctx.bot.get_chat_member(cid, clean)
            if m and m.user:
                return f"{clean} ({m.user.id})"
        except:
            pass
        return clean
    return clean

async def del_msg(u: Update):
    try:
        if u.message:
            await u.message.delete()
    except:
        pass

async def send_calc(u: Update, amt: float):
    fee, rate, _, rcv = calc_fee(amt)
    await u.message.reply_text(
        f"📊 <b>@CHIKUESCROWSERVICE FEE CALCULATOR</b>\n━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Deal Amount:</b> ₹{amt:,.0f}\n⚡ <b>Fee Rate:</b> {rate}\n"
        f"💵 <b>Escrow Fee:</b> ₹{fee:,.0f}\n━━━━━━━━━━━━━━━━━━━\n"
        f"✅ <b>Seller Receives:</b> ₹{rcv:,.0f}\n\n📱 <b>RG :</b> @CHIKUNXT",
        parse_mode="HTML"
    )

async def cmd_form(u: Update, c: ContextTypes.DEFAULT_TYPE):
    msg = (
        "<b>ᴇꜱᴄʀᴏᴡ ᴅᴇᴀʟ ғᴏʀᴍ</b>\n\n"
        "• <b>ꜱᴇʟʟᴇʀ :</b> \n\n"
        "• <b>ʙᴜʏᴇʀ :</b> \n\n"
        "• <b>ᴅᴇᴀʟ ᴅᴇᴀᴛᴀɪʟꜱ :</b> \n\n"
        "• <b>ᴅᴇᴀʟ ᴀᴍᴏᴜɴᴛ :</b> \n\n"
        "• <b>ᴇꜱᴄʀᴏᴡ ᴛɪʟʟ :</b> \n\n"
        "• <b>ғᴏʀ ʀᴇʟᴇᴀsᴇ sᴇʟʟᴇʀ ᴜᴘɪ :</b> \n\n"
        "<i>ғᴏʀ ᴍᴏʀᴇ ᴘʀᴏᴏғs ᴄʜᴇᴄᴋ ɢʀᴏᴜᴘ ᴘɪɴ ᴍᴇssᴀɢᴇs..</i>\n\n"
        "⚠️ <b>ESCROW FEES IS NON - REFUNDABLE NO MATTER IF THE DEAL GETS CANCELLED</b> ⚠️"
    )
    await u.message.reply_text(msg, parse_mode="HTML")

async def cmd_fee(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not c.args:
        await u.message.reply_text(
            "<b>@CHIKUESCROWSERVICE CHARGES -</b>\n\n"
            "• Under ₹190 - ₹10\n• ₹191 To ₹599 - ₹20\n• ₹600 To ₹2000 - 3.5%\n"
            "• ₹2001 To ₹3000 - 3%\n• Upper Than ₹3000 - 3%\n\n"
            "📱 <b>RG :</b> @CHIKUNXT\n━━━━━━━━━━━━━━━━━━━\n💡 Check amount: <code>fees 2000</code>",
            parse_mode="HTML"
        )
        return
    amt = get_amt(c.args[0])
    if amt > 0:
        await send_calc(u, amt)

async def cmd_deal(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global DEAL_CTR, CURR_DEAL, LAST_PIN
    if not await is_admin(u, c):
        return
    rep = u.message.reply_to_message
    if not rep or not (rep.text or rep.caption):
        await u.message.reply_text("⚠️ Bhare hue <b>FORM</b> ka reply karke <code>/deal</code> bhejo!", parse_mode="HTML")
        return
    try:
        await c.bot.unpin_chat_message(chat_id=u.effective_chat.id, message_id=rep.message_id)
    except:
        pass

    raw_text = rep.text or rep.caption
    f = parse_form(raw_text)
    seller = await resolve_user(f["seller"] or "N/A", rep, c, u.effective_chat.id)
    buyer = await resolve_user(f["buyer"] or "N/A", rep, c, u.effective_chat.id)

    amt = get_amt(f["amount"])
    fee_val, _, fee_tag, _ = calc_fee(amt)
    fee_line = f"\n\nFees {fee_tag}" if amt > 0 else ""
    did = f"DL-CHIKU-{DEAL_CTR:02d}"
    DEAL_CTR += 1
    CURR_DEAL = did
    eu = u.effective_user

    amt_lbl = f"₹{amt:,.0f}" if amt > 0 else (f['amount'] if f['amount'] else 'N/A')
    dtl = f['details'] if f['details'] else 'N/A'
    till = f['till'] if f['till'] else 'SECURE'

    msg = (
        f"<b>ESCROW DEAL</b>\n🪪 <b>DEAL ID:</b> {did}\n\n"
        f"• <b>ꜱᴇʟʟᴇʀ :</b> {seller}\n• <b>ʙᴜʏᴇʀ  :</b> {buyer}\n\n"
        f"• <b>ᴅᴇᴀʟ ᴅᴇᴀᴛᴀɪʟꜱ :</b> {dtl}\n• <b>ᴅᴇᴀʟ ᴀᴍᴏᴜɴᴛ :</b> {amt_lbl}\n"
        f"• <b>ᴇꜱᴄʀᴏᴡ ᴛɪʟʟ :</b> {till}\n\n"
        f"<b>Escrower :</b> {eu.mention_html()} ({eu.id}){fee_line}"
    )
    sm = await c.bot.send_message(chat_id=u.effective_chat.id, text=msg, parse_mode="HTML")
    try:
        await c.bot.pin_chat_message(chat_id=u.effective_chat.id, message_id=sm.message_id, disable_notification=True)
        LAST_PIN = sm.message_id
    except:
        pass
    DEALS_DB[did] = {"status": "ACTIVE", "seller": seller, "buyer": buyer, "amount": amt, "fee": fee_val, "escrower": (f"@{eu.username}" if eu.username else eu.first_name), "details": dtl, "msg_id": sm.message_id}

async def cmd_close(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global CURR_DEAL, LAST_PIN
    await del_msg(u)
    if not await is_admin(u, c):
        return
    cid = u.effective_chat.id
    rep = u.message.reply_to_message
    did, amt, seller, buyer, r_mid = None, 0.0, "", "", None

    if rep and (rep.text or rep.caption):
        r_mid = rep.message_id
        f = parse_form(rep.text or rep.caption)
        did = f["id"]
        if did and did in DEALS_DB:
            amt = DEALS_DB[did]["amount"]
            seller = DEALS_DB[did]["seller"]
            buyer = DEALS_DB[did]["buyer"]
            r_mid = DEALS_DB[did].get("msg_id", r_mid)
        else:
            amt = get_amt(f["amount"])
            seller = f["seller"]
            buyer = f["buyer"]

    if not did and CURR_DEAL and CURR_DEAL in DEALS_DB:
        did = CURR_DEAL
        amt = DEALS_DB[did]["amount"]
        seller = DEALS_DB[did]["seller"]
        buyer = DEALS_DB[did]["buyer"]
        r_mid = DEALS_DB[did].get("msg_id")

    if c.args and amt == 0.0:
        amt = get_amt(c.args[0])

    s_tag = seller.split()[0] if seller else "@Seller"
    b_tag = buyer.split()[0] if buyer else "@Buyer"
    did = did or "DL-CHIKU-01"
    eu = u.effective_user

    STATS["deals"] += 1
    STATS["vol"] += amt
    STATS["fees"] += calc_fee(amt)[0]

    target = r_mid or LAST_PIN
    if target:
        try:
            await c.bot.unpin_chat_message(chat_id=cid, message_id=target)
        except:
            pass

    amt_lbl = f"₹{amt:,.2f}" if amt > 0 else "Deal Amount"
    esc_by = f"@{eu.username}" if eu.username else eu.mention_html()
    txt = (
        f"✅ <b>Deal Completed</b>\n🪪 <b>Trade ID:</b>\n{did}\n"
        f"📤 <b>Released:</b> {amt_lbl}\n👤 <b>Escrowed By:</b>\n{esc_by}\n\n"
        f"~ {b_tag} and {s_tag}\nare requested to drop the\nvouch before leaving 👇🏻\n\n"
        f"<code>Vouch @chikuescrowservice for {amt_lbl} smooth escrow deal</code>"
    )
    sm = await c.bot.send_message(chat_id=cid, text=txt, parse_mode="HTML")
    try:
        await c.bot.pin_chat_message(chat_id=cid, message_id=sm.message_id, disable_notification=True)
        LAST_PIN = sm.message_id
    except:
        pass

async def cmd_cancel(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await del_msg(u)
    if not await is_admin(u, c):
        return
    did = CURR_DEAL or "DL-CHIKU-01"
    sm = await c.bot.send_message(chat_id=u.effective_chat.id, text=f"❌ <b>DEAL CANCELLED</b>\n🪪 <b>ID:</b> {did}\n👤 <b>By:</b> {u.effective_user.mention_html()}", parse_mode="HTML")
    try:
        await c.bot.pin_chat_message(chat_id=u.effective_chat.id, message_id=sm.message_id, disable_notification=True)
    except:
        pass

async def cmd_stats(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(
        f"📈 <b>@CHIKUESCROWSERVICE STATS</b>\n━━━━━━━━━━━━━━━━━━━\n"
        f"🤝 <b>Total Deals:</b> {STATS['deals']}\n"
        f"💼 <b>Total Volume:</b> ₹{STATS['vol']:,.2f}\n"
        f"💵 <b>Total Fees:</b> ₹{STATS['fees']:,.2f}",
        parse_mode="HTML"
    )

async def clean_pin_service(u: Update, c: ContextTypes.DEFAULT_TYPE):
    try:
        if u.message and u.message.pinned_message:
            await u.message.delete()
    except:
        pass

async def check_edit(u: Update, c: ContextTypes.DEFAULT_TYPE):
    em = u.edited_message
    if not em or not em.from_user or em.from_user.id == OWNER_ID:
        return
    try:
        admins = await c.bot.get_chat_administrators(em.chat_id)
        if any(a.user.id == em.from_user.id for a in admins):
            return
    except:
        pass
    try:
        await em.delete()
        await c.bot.send_message(chat_id=em.chat_id, text=f"⚠️ {em.from_user.mention_html()} <b>EDITED FORM/MESSAGE NOT ALLOWED ⚠️</b>", parse_mode="HTML")
    except:
        pass

async def text_router(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not u.message or not u.message.text:
        return
    t = u.message.text.strip().lower()
    if t in ["form", ".form"]:
        await cmd_form(u, c)
    elif t in ["fee", "fees", ".fee", ".fees"]:
        await cmd_fee(u, c)
    m = re.match(r"^(?:fee|fees|\.fee|\.fees|\/fee|\/fees)\s+([^\s]+)", t)
    if m:
        val = get_amt(m.group(1))
        if val > 0:
            await send_calc(u, val)

def main():
    threading.Thread(target=run_web, daemon=True).start()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("form", cmd_form))
    app.add_handler(CommandHandler("fee", cmd_fee))
    app.add_handler(CommandHandler("fees", cmd_fee))
    app.add_handler(CommandHandler("deal", cmd_deal))
    app.add_handler(CommandHandler("close", cmd_close))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(MessageHandler(filters.StatusUpdate.PINNED_MESSAGE, clean_pin_service))
    app.add_handler(MessageHandler(filters.UpdateType.EDITED_MESSAGE, check_edit))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
        

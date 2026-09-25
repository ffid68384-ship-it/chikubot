import os, re, unicodedata, threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

web_app = Flask(__name__)
@web_app.route('/')
def home():
    return "Chiku Escrow Active"

def run_web():
    web_app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8938665546:AAH-1KMv8sD33fEXGPGYWmLkA9ZYIxfKJ8I")
OWNER_ID = 7364435907
DEALS_DB, STATS = {}, {"deals": 0, "vol": 0.0, "fees": 0.0}
DEAL_CTR, CURR_DEAL, LAST_PIN = 11250, None, None

async def is_admin(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not u.effective_user or u.effective_user.id == OWNER_ID or u.effective_chat.type == "private":
        return True
    try:
        admins = await c.bot.get_chat_administrators(u.effective_chat.id)
        return any(a.user.id == u.effective_user.id for a in admins)
    except:
        return True

MAP = {
    'ɢ':'g','ɪ':'i','ɴ':'n','ʀ':'r','ʏ':'y','ʙ':'b','ʜ':'h','ʟ':'l','ꜱ':'s','ғ':'f',
    'ᴀ':'a','ᴄ':'c','ᴅ':'d','ᴇ':'e','ᴋ':'k','ᴍ':'m','ᴏ':'o','ᴘ':'p','ᴛ':'t','ᴜ':'u',
    'ᴡ':'w','ᴊ':'j','ǫ':'q','ᴠ':'v','ᴢ':'z','𝖴':'u','U':'u','O':'o','О':'o','а':'a',
    'е':'e','о':'o','р':'p','с':'c','у':'y','х':'x','м':'m','н':'n','т':'t'
}

def clean_txt(t):
    if not t: return ""
    norm = unicodedata.normalize('NFKD', str(t))
    return "".join(MAP.get(ch, ch) for ch in norm).lower()

def calc_fee(amt):
    if amt <= 0: return 0.0, "0%", "0₹", 0.0
    if amt <= 190: return 10.0, "Flat ₹10", "Rs 10", amt - 10.0
    if amt <= 599: return 20.0, "Flat ₹20", "Rs 20", amt - 20.0
    if amt <= 2000:
        f = round(amt * 0.035, 2)
        return f, "3.5%", f"3.5% - {round(f)}₹", amt - f
    f = round(amt * 0.03, 2)
    return f, "3%", f"3% - {round(f)}₹", amt - f

def parse_form(raw):
    d = {"seller": "", "buyer": "", "details": "", "amount": 0.0, "till": "", "id": ""}
    if not raw: return d
    c_full = clean_txt(raw)
    
    m_id = re.search(r"dl[-_ ]*chiku[-_ ]*(\d+)", c_full, re.I)
    if m_id: d["id"] = f"DL-CHIKU-{m_id.group(1)}"
    
    r_lines, c_lines = raw.split('\n'), c_full.split('\n')
    for i, (r_l, c_l) in enumerate(zip(r_lines, c_lines)):
        if not c_l.strip(): continue
        val = r_l.split(':', 1)[1].strip() if ':' in r_l else (r_l.split('-', 1)[1].strip() if '-' in r_l else "")
        lbl = re.sub(r'^[•\*\-\s]+', '', c_l.split(':', 1)[0] if ':' in c_l else c_l.split('-', 1)[0]).strip()
        
        if (lbl in ['seller', 's'] or lbl.endswith(' seller')) and not d['seller']:
            d['seller'] = val
        elif (lbl in ['buyer', 'b'] or lbl.endswith(' buyer')) and not d['buyer']:
            d['buyer'] = val
        elif any(k in lbl for k in ['detail', 'deatail']) and not d['details']:
            d['details'] = val
            if i + 1 < len(r_lines):
                nxt = c_lines[i+1].strip()
                if nxt and not any(k in nxt for k in ['•', '*', '-', ':', 'amount', 'amt', 'till', 'escrow', 'seller', 'buyer']):
                    d['details'] += " " + r_lines[i+1].strip()
        elif any(k in lbl for k in ['amount', 'amt', 'price', 'cost']) and d['amount'] == 0.0:
            m = re.search(r'(\d+(?:\.\d+)?)', clean_txt(val).replace(',', ''))
            if m: d['amount'] = float(m.group(1))
        elif 'till' in lbl and not d['till']:
            d['till'] = val

    if d['amount'] == 0.0:
        no_u = re.sub(r'@\w+', '', c_full).replace(',', '')
        m_amt = re.search(r'(?:amount|amt|price)[\s\:\-]*[₹rs\s]*(\d+(?:\.\d+)?)', no_u)
        if m_amt: d['amount'] = float(m_amt.group(1))
        else:
            m_curr = re.search(r'[₹rs]\s*(\d+(?:\.\d+)?)', no_u)
            if m_curr: d['amount'] = float(m_curr.group(1))
    return d

async def resolve_u(u, rep, ctx, cid):
    if not u or u.upper() == "N/A": return u or "N/A"
    clean = u.strip()
    if "(" in clean and ")" in clean: return clean
    if clean.isdigit(): return f'<a href="tg://user?id={clean}">{clean}</a> ({clean})'
    if clean.lower() in ["me", "i", "myself", "mai"] and rep and rep.from_user:
        fu = rep.from_user
        return f"@{fu.username} ({fu.id})" if fu.username else f"{fu.first_name} ({fu.id})"
    if rep and rep.entities:
        for ent in rep.entities:
            if ent.type == "text_mention" and ent.user:
                return f'{ent.user.mention_html()} ({ent.user.id})'
    if clean.startswith("@"):
        try:
            m = await ctx.bot.get_chat_member(cid, clean)
            if m and m.user: return f"{clean} ({m.user.id})"
        except: pass
    return clean

async def del_m(u: Update):
    try:
        if u.message: await u.message.delete()
    except: pass

async def send_c(u: Update, amt: float):
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
        "<b>ᴇꜱᴄʀᴏᴡ ᴅᴇᴀʟ ғᴏʀᴍ</b>\n\n• <b>ꜱᴇʟʟᴇʀ :</b> \n\n• <b>ʙᴜʏᴇʀ :</b> \n\n"
        "• <b>ᴅᴇᴀʟ ᴅᴇᴀᴛᴀɪʟꜱ :</b> \n\n• <b>ᴅᴇᴀʟ ᴀᴍᴏᴜɴᴛ :</b> \n\n• <b>ᴇꜱᴄʀᴏᴡ ᴛɪʟʟ :</b> \n\n"
        "• <b>ғᴏʀ ʀᴇʟᴇᴀsᴇ sᴇʟʟᴇʀ ᴜᴘɪ :</b> \n\n<i>ғᴏʀ ᴍᴏʀᴇ ᴘʀᴏᴏғs ᴄʜᴇᴄᴋ ɢʀᴏᴜᴘ ᴘɪɴ ᴍᴇssᴀɢᴇs..</i>\n\n"
        "⚠️ <b>ESCROW FEES IS NON - REFUNDABLE NO MATTER IF THE DEAL GETS CANCELLED</b> ⚠️"
    )
    await u.message.reply_text(msg, parse_mode="HTML")

async def cmd_fee(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not c.args:
        await u.message.reply_text(
            "<b>@CHIKUESCROWSERVICE CHARGES -</b>\n\n• Under ₹190 - ₹10\n• ₹191 To ₹599 - ₹20\n"
            "• ₹600 To ₹2000 - 3.5%\n• ₹2001 To ₹3000 - 3%\n• Upper Than ₹3000 - 3%\n\n"
            "📱 <b>RG :</b> @CHIKUNXT\n━━━━━━━━━━━━━━━━━━━\n💡 Check: <code>fees 2000</code>",
            parse_mode="HTML"
        )
        return
    num = re.sub(r'[^\d\.]', '', c.args[0])
    if num and float(num) > 0: await send_c(u, float(num))

async def cmd_deal(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global DEAL_CTR, CURR_DEAL, LAST_PIN
    if not await is_admin(u, c): return
    rep = u.message.reply_to_message
    if not rep or not (rep.text or rep.caption):
        await u.message.reply_text("⚠️ Bhare hue <b>FORM</b> ka reply karke <code>/deal</code> bhejo!", parse_mode="HTML")
        return
    try: await c.bot.unpin_chat_message(chat_id=u.effective_chat.id, message_id=rep.message_id)
    except: pass

    f = parse_form(rep.text or rep.caption)
    if c.args:
        n = re.sub(r'[^\d\.]', '', c.args[0])
        if n: f["amount"] = float(n)

    seller = await resolve_u(f["seller"] or "N/A", rep, c, u.effective_chat.id)
    buyer = await resolve_u(f["buyer"] or "N/A", rep, c, u.effective_chat.id)
    amt = f["amount"]
    fee_val, _, fee_tag, _ = calc_fee(amt)
    fee_line = f"\n\nFees {fee_tag}" if amt > 0 else ""
    
    did = f"DL-CHIKU-{DEAL_CTR}"
    DEAL_CTR += 1
    CURR_DEAL = did
    eu = u.effective_user

    amt_lbl = f"₹{amt:,.0f}" if amt > 0 else "Deal Amount"
    dtl = f['details'] if f['details'] else 'N/A'
    till = f['till'] if f['till'] else 'SECURE'

    msg = (
        f"<b>ESCROW DEAL</b>\n🪪 <b>DEAL ID:</b> {did}\n\n• <b>ꜱᴇʟʟᴇʀ :</b> {seller}\n• <b>ʙᴜʏᴇʀ  :</b> {buyer}\n\n"
        f"• <b>ᴅᴇᴀʟ ᴅᴇᴀᴛᴀɪʟꜱ :</b> {dtl}\n• <b>ᴅᴇᴀʟ ᴀᴍᴏᴜɴᴛ :</b> {amt_lbl}\n• <b>ᴇꜱᴄʀᴏᴡ ᴛɪʟʟ :</b> {till}\n\n"
        f"<b>Escrower :</b> {eu.mention_html()} ({eu.id}){fee_line}"
    )
    sm = await c.bot.send_message(chat_id=u.effective_chat.id, text=msg, parse_mode="HTML")
    try:
        await c.bot.pin_chat_message(chat_id=u.effective_chat.id, message_id=sm.message_id, disable_notification=True)
        LAST_PIN = sm.message_id
    except: pass
    DEALS_DB[did] = {"status": "ACTIVE", "seller": seller, "buyer": buyer, "amount": amt, "escrower": (f"@{eu.username}" if eu.username else eu.first_name), "details": dtl, "msg_id": sm.message_id}

async def cmd_received(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(u, c): return
    cid, rep = u.effective_chat.id, u.message.reply_to_message
    did, amt, seller, buyer = None, 0.0, "", ""

    if rep and (rep.text or rep.caption):
        f = parse_form(rep.text or rep.caption)
        did = f["id"]
        amt = f["amount"] if f["amount"] > 0 else (DEALS_DB.get(did, {}).get("amount", 0.0) if did in DEALS_DB else 0.0)
        seller = f["seller"] if f["seller"] else (DEALS_DB.get(did, {}).get("seller", "") if did in DEALS_DB else "")
        buyer = f["buyer"] if f["buyer"] else (DEALS_DB.get(did, {}).get("buyer", "") if did in DEALS_DB else "")

    if not did and CURR_DEAL and CURR_DEAL in DEALS_DB:
        did = CURR_DEAL
        if amt == 0.0: amt = DEALS_DB[did]["amount"]
        if not seller: seller = DEALS_DB[did]["seller"]
        if not buyer: buyer = DEALS_DB[did]["buyer"]

    did = did or CURR_DEAL or f"DL-CHIKU-{DEAL_CTR}"
    amt_lbl = f"₹{amt:,.0f}" if amt > 0 else "Deal Amount"
    s_tag = seller.split()[0] if seller else "@Seller"
    b_tag = buyer.split()[0] if buyer else "@Buyer"

    msg = (
        f"💰 <b>PAYMENT RECEIVED & CONFIRMED!</b>\n━━━━━━━━━━━━━━━━━━━\n"
        f"🪪 <b>Deal ID:</b> {did}\n💵 <b>Amount:</b> {amt_lbl}\n👤 <b>Buyer:</b> {b_tag}\n👤 <b>Seller:</b> {s_tag}\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n🤝 <b>TRANSFER ACCESS TO BUYER WITH SCREENRECORDS !!</b> 🤝\n\n"
        f"⚠️ <i>Seller video record karke access transfer karein aur Buyer verify karke vouch karein.</i>"
    )
    await c.bot.send_message(chat_id=cid, text=msg, parse_mode="HTML")

async def cmd_close(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global CURR_DEAL, LAST_PIN
    await del_m(u)
    if not await is_admin(u, c): return
    cid, rep = u.effective_chat.id, u.message.reply_to_message
    did, amt, seller, buyer, r_mid = None, 0.0, "", "", None

    if rep and (rep.text or rep.caption):
        r_mid = rep.message_id
        f = parse_form(rep.text or rep.caption)
        did, amt, seller, buyer = f["id"], f["amount"], f["seller"], f["buyer"]
        if did and did in DEALS_DB:
            r_mid = DEALS_DB[did].get("msg_id", r_mid)
            if amt == 0.0: amt = DEALS_DB[did].get("amount", 0.0)
            if not seller: seller = DEALS_DB[did].get("seller", "")
            if not buyer: buyer = DEALS_DB[did].get("buyer", "")

    if not did and CURR_DEAL and CURR_DEAL in DEALS_DB:
        did = CURR_DEAL
        if amt == 0.0: amt = DEALS_DB[did]["amount"]
        if not seller: seller = DEALS_DB[did]["seller"]
        if not buyer: buyer = DEALS_DB[did]["buyer"]
        r_mid = DEALS_DB[did].get("msg_id")

    if c.args:
        n = re.sub(r'[^\d\.]', '', c.args[0])
        if n and float(n) > 0: amt = float(n)

    s_tag = seller.split()[0] if seller else "@Seller"
    b_tag = buyer.split()[0] if buyer else "@Buyer"
    did = did or CURR_DEAL or f"DL-CHIKU-{DEAL_CTR}"
    eu = u.effective_user

    STATS["deals"] += 1
    STATS["vol"] += amt
    STATS["fees"] += calc_fee(amt)[0]
    if did in DEALS_DB: DEALS_DB[did]["status"] = "COMPLETED"

    target = r_mid or LAST_PIN
    if target:
        try: await c.bot.unpin_chat_message(chat_id=cid, message_id=target)
        except: pass

    amt_lbl = f"₹{amt:,.2f}" if amt > 0 else "Deal Amount"
    esc_by = f"@{eu.username}" if eu.username else eu.mention_html()
    txt = (
        f"✅ <b>Deal Completed</b>\n🪪 <b>Trade ID:</b>\n{did}\n📤 <b>Released:</b> {amt_lbl}\n"
        f"👤 <b>Escrowed By:</b>\n{esc_by}\n\n~ {b_tag} and {s_tag}\nare requested to drop the\nvouch before leaving 👇🏻\n\n"
        f"<code>Vouch @chikuescrowservice for {amt_lbl} smooth escrow deal</code>"
    )
    sm = await c.bot.send_message(chat_id=cid, text=txt, parse_mode="HTML")
    try:
        await c.bot.pin_chat_message(chat_id=cid, message_id=sm.message_id, disable_notification=True)
        LAST_PIN = sm.message_id
    except: pass

async def cmd_cancel(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global LAST_PIN
    await del_m(u)
    if not await is_admin(u, c): return
    did = CURR_DEAL or f"DL-CHIKU-{DEAL_CTR}"
    if did in DEALS_DB: DEALS_DB[did]["status"] = "CANCELLED"
    sm = await c.bot.send_message(chat_id=u.effective_chat.id, text=f"❌ <b>DEAL CANCELLED</b>\n🪪 <b>ID:</b> {did}\n👤 <b>By:</b> {u.effective_user.mention_html()}", parse_mode="HTML")
    try:
        await c.bot.pin_chat_message(chat_id=u.effective_chat.id, message_id=sm.message_id, disable_notification=True)
        LAST_PIN = sm.message_id
    except: pass

async def cmd_hold(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global LAST_PIN
    await del_m(u)
    if not await is_admin(u, c): return
    did = CURR_DEAL or f"DL-CHIKU-{DEAL_CTR}"
    if did in DEALS_DB: DEALS_DB[did]["status"] = "ON HOLD"
    rsn = " ".join(c.args) if c.args else "Verification / Dispute Under Review"
    sm = await c.bot.send_message(chat_id=u.effective_chat.id, text=f"⏳ <b>DEAL ON HOLD</b>\n━━━━━━━━━━━━━━━━━━━\n🪪 <b>Deal ID:</b> {did}\n⚠️ <b>Reason:</b> {rsn}\n👤 <b>Action By:</b> {u.effective_user.mention_html()}\n\n🔒 <i>Release is paused.</i>", parse_mode="HTML")
    try:
        await c.bot.pin_chat_message(chat_id=u.effective_chat.id, message_id=sm.message_id, disable_notification=True)
        LAST_PIN = sm.message_id
    except: pass

async def cmd_adminhold(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(u, c): return
    hd = {k: v for k, v in DEALS_DB.items() if v.get("status") in ["ACTIVE", "ON HOLD"]}
    if not hd:
        await u.message.reply_text("🛡️ <b>ADMIN HOLD STATUS</b>\n━━━━━━━━━━━━━━━━━━━\nAbhi koi active hold deal nahi hai.", parse_mode="HTML")
        return
    ag, gtot = {}, 0.0
    for did, info in hd.items():
        adm = info.get("escrower", "Unknown Escrower")
        ag.setdefault(adm, []).append((did, info))
        gtot += info.get("amount", 0.0)
    out = ["🛡️ <b>ADMIN HOLD STATUS</b>\n━━━━━━━━━━━━━━━━━━━\n"]
    for adm, deals in ag.items():
        total_adm = sum(d[1].get("amount", 0.0) for d in deals)
        out.append(f"👤 <b>{adm}</b> — Hold: ₹{total_adm:,.2f}")
        for did, d in deals:
            amt = d.get("amount", 0.0)
            _, rate, _, net = calc_fee(amt)
            out.append(f"  • <b>{did}</b> — ₹{amt:,.0f} ({d.get('status')})\n    Fee: {rate} | Net: ₹{net:,.0f}")
        out.append("")
    out.append("───────────────────")
    out.append(f"💰 <b>TOTAL HOLD ACROSS ALL ADMINS: ₹{gtot:,.2f}</b>")
    await u.message.reply_text("\n".join(out), parse_mode="HTML")

async def cmd_stats(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(
        f"📈 <b>@CHIKUESCROWSERVICE STATS</b>\n━━━━━━━━━━━━━━━━━━━\n"
        f"🤝 <b>Total Deals:</b> {STATS['deals']}\n💼 <b>Total Volume:</b> ₹{STATS['vol']:,.2f}\n"
        f"💵 <b>Total Fees:</b> ₹{STATS['fees']:,.2f}\n📱 <b>RG :</b> @CHIKUNXT",
        parse_mode="HTML"
    )

async def clean_pin(u: Update, c: ContextTypes.DEFAULT_TYPE):
    try:
        if u.message and u.message.pinned_message: await u.message.delete()
    except: pass

async def check_edit(u: Update, c: ContextTypes.DEFAULT_TYPE):
    em = u.edited_message
    if not em or not em.from_user or em.from_user.id == OWNER_ID: return
    try:
        admins = await c.bot.get_chat_administrators(em.chat_id)
        if any(a.user.id == em.from_user.id for a in admins): return
    except: pass
    try:
        await em.delete()
        await c.bot.send_message(chat_id=em.chat_id, text=f"⚠️ {em.from_user.mention_html()} <b>EDITED FORM/MESSAGE NOT ALLOWED ⚠️</b>", parse_mode="HTML")
    except: pass

async def text_router(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not u.message or not u.message.text: return
    t = u.message.text.strip().lower()
    if t in ["form", ".form"]: await cmd_form(u, c)
    elif t in ["fee", "fees", ".fee", ".fees"]: await cmd_fee(u, c)
    elif t in ["stats", ".stats", "/stats"]: await cmd_stats(u, c)
    elif t in ["adminhold", ".adminhold", "/adminhold"]: await cmd_adminhold(u, c)
    elif t in ["received", ".received", "recieved", ".recieved", "receive", ".receive", "recive", ".recive"]:
        await cmd_received(u, c)
    m = re.match(r"^(?:fee|fees|\.fee|\.fees|\/fee|\/fees)\s+([^\s]+)", t)
    if m:
        n = re.sub(r'[^\d\.]', '', m.group(1))
        if n and float(n) > 0: await send_c(u, float(n))

def main():
    threading.Thread(target=run_web, daemon=True).start()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    for cmd in ["form"]: app.add_handler(CommandHandler(cmd, cmd_form))
    for cmd in ["fee", "fees"]: app.add_handler(CommandHandler(cmd, cmd_fee))
    for cmd in ["deal"]: app.add_handler(CommandHandler(cmd, cmd_deal))
    for cmd in ["received", "recieved", "receive", "recive"]: app.add_handler(CommandHandler(cmd, cmd_received))
    for cmd in ["close"]: app.add_handler(CommandHandler(cmd, cmd_close))
    for cmd in ["cancel"]: app.add_handler(CommandHandler(cmd, cmd_cancel))
    for cmd in ["hold"]: app.add_handler(CommandHandler(cmd, cmd_hold))
    for cmd in ["adminhold"]: app.add_handler(CommandHandler(cmd, cmd_adminhold))
    for cmd in ["stats"]: app.add_handler(CommandHandler(cmd, cmd_stats))
    app.add_handler(MessageHandler(filters.StatusUpdate.PINNED_MESSAGE, clean_pin))
    app.add_handler(MessageHandler(filters.UpdateType.EDITED_MESSAGE, check_edit))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
    

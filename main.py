import os, re, sqlite3, unicodedata, threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

web_app = Flask(__name__)
@web_app.route('/')
def home(): return "Chiku Escrow 24/7 Live"

def run_web():
    web_app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8938665546:AAH-1KMv8sD33fEXGPGYWmLkA9ZYIxfKJ8I")
OWNER_ID, DB_FILE, LAST_PIN = 7364435907, "escrow.db", None

def db_run(q, p=(), fetch=None):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute(q, p)
        res = c.fetchall() if fetch == "all" else (c.fetchone() if fetch == "one" else None)
        conn.commit()
        return res

db_run('CREATE TABLE IF NOT EXISTS deals (did TEXT PRIMARY KEY, status TEXT, seller TEXT, buyer TEXT, amt REAL, fee REAL, escrower TEXT, msg_id INTEGER)')
db_run('CREATE TABLE IF NOT EXISTS stats (id INTEGER PRIMARY KEY, deals INTEGER, vol REAL, fees REAL)')
db_run('CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v INTEGER)')
db_run('INSERT OR IGNORE INTO stats VALUES (1, 11, 9705.0, 350.0)')
db_run('INSERT OR IGNORE INTO meta VALUES ("ctr", 11257)')

def get_next_did():
    curr = db_run('SELECT v FROM meta WHERE k = "ctr"', fetch="one")[0]
    db_run('UPDATE meta SET v = ? WHERE k = "ctr"', (curr + 1,))
    return f"DL-CHIKU-{curr}"

async def is_admin(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not u.effective_user or u.effective_user.id == OWNER_ID or u.effective_chat.type == "private": return True
    try:
        admins = await c.bot.get_chat_administrators(u.effective_chat.id)
        return any(a.user.id == u.effective_user.id for a in admins)
    except: return True

async def is_owner(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not u.effective_user: return False
    return u.effective_user.id == OWNER_ID

def clean_txt(t):
    return unicodedata.normalize('NFKD', str(t or "")).encode('ascii', 'ignore').decode('utf-8').lower()

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
    d = {"seller": "N/A", "buyer": "N/A", "details": "N/A", "amount": 0.0, "till": "SECURE", "id": ""}
    if not raw: return d
    cf = clean_txt(raw)
    m_id = re.search(r"dl[-_ ]*chiku[-_ ]*(\d+)", cf, re.I)
    if m_id: d["id"] = f"DL-CHIKU-{m_id.group(1)}"
    rl, cl = raw.split('\n'), cf.split('\n')
    for i, (r, c) in enumerate(zip(rl, cl)):
        if not c.strip(): continue
        val = r.split(':', 1)[1].strip() if ':' in r else (r.split('-', 1)[1].strip() if '-' in r else "")
        lbl = re.sub(r'^[•\*\-\s]+', '', c.split(':', 1)[0] if ':' in c else c.split('-', 1)[0]).strip()
        if (lbl in ['seller', 's'] or lbl.endswith(' seller')) and val: d['seller'] = val
        elif (lbl in ['buyer', 'b'] or lbl.endswith(' buyer')) and val: d['buyer'] = val
        elif 'detail' in lbl:
            if val: d['details'] = val
            if i + 1 < len(rl) and cl[i+1].strip() and not any(k in cl[i+1] for k in ['•','*','-',':','amount','amt','till','escrow']): 
                d['details'] += " " + rl[i+1].strip()
        elif any(k in lbl for k in ['amount', 'amt', 'price', 'cost']):
            m = re.search(r'(\d+(?:\.\d+)?)', clean_txt(val).replace(',', ''))
            if m: d['amount'] = float(m.group(1))
        elif 'till' in lbl and val: d['till'] = val
    if d['amount'] == 0.0:
        no_u = re.sub(r'@\w+', '', cf).replace(',', '')
        m_amt = re.search(r'(?:amount|amt|price)[\s\:\-]*[₹rs\s]*(\d+(?:\.\d+)?)', no_u) or re.search(r'[₹rs]\s*(\d+(?:\.\d+)?)', no_u)
        if m_amt: d['amount'] = float(m_amt.group(1))
    return d

async def resolve_u(u, rep, ctx, cid):
    if not u or u.upper() == "N/A": return "N/A"
    clean = u.strip()
    if clean.isdigit(): return f'<a href="tg://user?id={clean}">{clean}</a> ({clean})'
    if clean.startswith("@"): return clean
    return clean

async def del_m(u: Update):
    try:
        if u.message: await u.message.delete()
    except: pass

async def send_c(u: Update, amt: float):
    fee, rate, _, rcv = calc_fee(amt)
    await u.message.reply_text(f"📊 <b>@CHIKUESCROWSERVICE FEE CALCULATOR</b>\n━━━━━━━━━━━━━━━━━━━\n💰 <b>Deal Amount:</b> ₹{amt:,.0f}\n⚡ <b>Fee Rate:</b> {rate}\n💵 <b>Escrow Fee:</b> ₹{fee:,.0f}\n━━━━━━━━━━━━━━━━━━━\n✅ <b>Seller Receives:</b> ₹{rcv:,.0f}\n\n📱 <b>RG :</b> @CHIKUNXT", parse_mode="HTML")

async def cmd_form(u: Update, c: ContextTypes.DEFAULT_TYPE):
    form_msg = (
        "<b>ᴇꜱᴄʀᴏᴡ ᴅᴇᴀʟ ғᴏʀᴍ</b>\n\n"
        "• <b>ꜱᴇʟʟᴇʀ :</b> \n\n"
        "• <b>ʙᴜʏᴇʀ :</b> \n\n"
        "• <b>ᴅᴇᴀʟ ᴅᴇᴀᴛᴀɪʟꜱ :</b> \n\n"
        "• <b>ᴅᴇᴀʟ ᴀᴍᴏᴜɴᴛ :</b> \n\n"
        "• <b>ᴇꜱᴄʀᴏᴡ ᴛɪʟʟ :</b> \n\n"
        "• <b>ғᴏʀ ʀᴇʟᴇᴀꜱᴇ ꜱᴇʟʟᴇʀ ᴜᴘɪ :</b> \n\n"
        "<b>ғᴏʀ ᴍᴏʀᴇ ᴘʀᴏᴏꜰꜱ ᴄʜᴇᴄᴋ ɢʀᴏᴜᴘ ᴘɪɴ ᴍᴇꜱꜱᴀɢᴇꜱ..</b>\n\n"
        "⚠️ <b>ESCROW FEES IS NON - REFUNDABLE NO MATTER IF THE DEAL GETS CANCELLED</b> ⚠️"
    )
    await u.message.reply_text(form_msg, parse_mode="HTML")

async def cmd_fee(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not c.args:
        await u.message.reply_text("<b>@CHIKUESCROWSERVICE CHARGES</b>\n\n• Under ₹190 - ₹10\n• ₹191 To ₹599 - ₹20\n• ₹600 To ₹2000 - 3.5%\n• ₹2001 To ₹3000 - 3%\n• Upper Than ₹3000 - 3%\n\n📱 <b>RG :</b> @CHIKUNXT\n💡 Check: <code>fees 2000</code>", parse_mode="HTML")
        return
    num = re.sub(r'[^\d\.]', '', c.args[0])
    if num and float(num) > 0: await send_c(u, float(num))

async def cmd_deal(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global LAST_PIN
    if not await is_admin(u, c): return
    rep = u.message.reply_to_message
    if not rep or not (rep.text or rep.caption):
        return await u.message.reply_text("⚠️ Bhare hue <b>FORM</b> ka reply karke <code>/deal</code> bhejo!", parse_mode="HTML")
    if LAST_PIN:
        try: await c.bot.unpin_chat_message(chat_id=u.effective_chat.id, message_id=LAST_PIN)
        except: pass
    f = parse_form(rep.text or rep.caption)
    if c.args:
        n = re.sub(r'[^\d\.]', '', c.args[0])
        if n: f["amount"] = float(n)
    seller = await resolve_u(f["seller"], rep, c, u.effective_chat.id)
    buyer = await resolve_u(f["buyer"], rep, c, u.effective_chat.id)
    amt, did, eu = f["amount"], get_next_did(), u.effective_user
    fee_val, _, fee_tag, _ = calc_fee(amt)
    esc_tag = (f"@{eu.username}" if eu.username else eu.first_name) if eu else "Admin"
    msg = f"<b>ESCROW DEAL</b>\n🪪 <b>DEAL ID:</b> {did}\n\n• <b>SELLER :</b> {seller}\n• <b>BUYER  :</b> {buyer}\n\n• <b>DEAL DETAILS :</b> {f['details']}\n• <b>DEAL AMOUNT :</b> ₹{amt:,.0f}\n• <b>ESCROW TILL :</b> {f['till']}\n\n<b>Escrower :</b> {esc_tag}\n\nFees {fee_tag}"
    sm = await c.bot.send_message(chat_id=u.effective_chat.id, text=msg, parse_mode="HTML")
    try:
        await c.bot.pin_chat_message(chat_id=u.effective_chat.id, message_id=sm.message_id, disable_notification=True)
        LAST_PIN = sm.message_id
    except: pass
    db_run('INSERT OR REPLACE INTO deals VALUES (?, "ACTIVE", ?, ?, ?, ?, ?, ?)', (did, seller, buyer, amt, fee_val, esc_tag, sm.message_id))

async def cmd_received(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(u, c): return
    rep = u.message.reply_to_message
    did, amt, seller, buyer = None, 0.0, "", ""
    if rep and (rep.text or rep.caption):
        f = parse_form(rep.text or rep.caption)
        did = f["id"]
        row = db_run('SELECT amt, seller, buyer FROM deals WHERE did = ?', (did,), "one") if did else None
        amt = f["amount"] if f["amount"] > 0 else (row[0] if row else 0.0)
        seller, buyer = (f["seller"] if f["seller"] != "N/A" else "") or (row[1] if row else ""), (f["buyer"] if f["buyer"] != "N/A" else "") or (row[2] if row else "")
    if not did:
        row = db_run('SELECT did, amt, seller, buyer FROM deals ORDER BY ROWID DESC LIMIT 1', fetch="one")
        if row: did, amt, seller, buyer = row[0], (amt or row[1]), (seller or row[2]), (buyer or row[3])
    msg = f"💰 <b>PAYMENT RECEIVED & CONFIRMED!</b>\n━━━━━━━━━━━━━━━━━━━\n🪪 <b>Deal ID:</b> {did or 'DL-ACTIVE'}\n💵 <b>Amount:</b> ₹{amt:,.0f}\n👤 <b>Buyer:</b> {buyer.split()[0] if buyer else '@Buyer'}\n👤 <b>Seller:</b> {seller.split()[0] if seller else '@Seller'}\n━━━━━━━━━━━━━━━━━━━\n\n🤝 <b>TRANSFER ACCESS TO BUYER WITH SCREENRECORDS !!</b> 🤝"
    await c.bot.send_message(chat_id=u.effective_chat.id, text=msg, parse_mode="HTML")

async def cmd_close(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global LAST_PIN
    await del_m(u)
    if not await is_admin(u, c): return
    cid, rep = u.effective_chat.id, u.message.reply_to_message
    did, amt, seller, buyer, r_mid = None, 0.0, "", "", None
    if rep and (rep.text or rep.caption):
        r_mid = rep.message_id
        f = parse_form(rep.text or rep.caption)
        did, amt, seller, buyer = f["id"], f["amount"], f["seller"], f["buyer"]
        row = db_run('SELECT amt, seller, buyer, msg_id FROM deals WHERE did = ?', (did,), "one") if did else None
        if row:
            r_mid, amt, seller, buyer = row[3] or r_mid, (amt if amt > 0 else row[0]), (seller if seller != "N/A" else row[1]), (buyer if buyer != "N/A" else row[2])
    if not did:
        row = db_run('SELECT did, amt, seller, buyer, msg_id FROM deals ORDER BY ROWID DESC LIMIT 1', fetch="one")
        if row: did, amt, seller, buyer, r_mid = row[0], (amt or row[1]), (seller or row[2]), (buyer or row[3]), row[4]
    if c.args:
        n = re.sub(r'[^\d\.]', '', c.args[0])
        if n and float(n) > 0: amt = float(n)
    db_run('UPDATE stats SET deals = deals + 1, vol = vol + ?, fees = fees + ? WHERE id = 1', (amt, calc_fee(amt)[0]))
    if did: db_run('UPDATE deals SET status = "COMPLETED" WHERE did = ?', (did,))
    target = r_mid or LAST_PIN
    if target:
        try: await c.bot.unpin_chat_message(chat_id=cid, message_id=target)
        except: pass
    eu = u.effective_user
    esc_by = (f"@{eu.username}" if eu.username else eu.mention_html()) if eu else "Admin"
    txt = f"✅ <b>Deal Completed</b>\n🪪 <b>Trade ID:</b>\n{did or 'DL-CHIKU'}\n📤 <b>Released:</b> ₹{amt:,.2f}\n👤 <b>Escrowed By:</b>\n{esc_by}\n\n<code>Vouch @chikuescrowservice for ₹{amt:,.0f} smooth escrow deal</code>"
    sm = await c.bot.send_message(chat_id=cid, text=txt, parse_mode="HTML")
    try:
        await c.bot.pin_chat_message(chat_id=cid, message_id=sm.message_id, disable_notification=True)
        LAST_PIN = sm.message_id
    except: pass

async def cmd_cancel(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global LAST_PIN
    await del_m(u)
    if not await is_admin(u, c): return
    row = db_run('SELECT did FROM deals ORDER BY ROWID DESC LIMIT 1', fetch="one")
    did = row[0] if row else "DL-ACTIVE"
    db_run('UPDATE deals SET status = "CANCELLED" WHERE did = ?', (did,))
    if LAST_PIN:
        try: await c.bot.unpin_chat_message(chat_id=u.effective_chat.id, message_id=LAST_PIN)
        except: pass
    sm = await c.bot.send_message(chat_id=u.effective_chat.id, text=f"❌ <b>DEAL CANCELLED</b>\n🪪 <b>ID:</b> {did}", parse_mode="HTML")
    try:
        await c.bot.pin_chat_message(chat_id=u.effective_chat.id, message_id=sm.message_id, disable_notification=True)
        LAST_PIN = sm.message_id
    except: pass

async def cmd_refund(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global LAST_PIN
    await del_m(u)
    if not await is_admin(u, c): return
    row = db_run('SELECT did, amt, buyer FROM deals ORDER BY ROWID DESC LIMIT 1', fetch="one")
    did, amt, buyer = row[0] if row else "DL-ACTIVE", row[1] if row else 0.0, row[2] if row else "@Buyer"
    db_run('UPDATE deals SET status = "REFUNDED" WHERE did = ?', (did,))
    if LAST_PIN:
        try: await c.bot.unpin_chat_message(chat_id=u.effective_chat.id, message_id=LAST_PIN)
        except: pass
    sm = await c.bot.send_message(chat_id=u.effective_chat.id, text=f"🔄 <b>DEAL REFUNDED</b>\n🪪 <b>Trade ID:</b> {did}\n💵 <b>Refunded Amount:</b> ₹{amt:,.2f}", parse_mode="HTML")
    try:
        await c.bot.pin_chat_message(chat_id=u.effective_chat.id, message_id=sm.message_id, disable_notification=True)
        LAST_PIN = sm.message_id
    except: pass

async def cmd_hold(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global LAST_PIN
    await del_m(u)
    if not await is_admin(u, c): return
    row = db_run('SELECT did FROM deals ORDER BY ROWID DESC LIMIT 1', fetch="one")
    did = row[0] if row else "DL-ACTIVE"
    db_run('UPDATE deals SET status = "ON HOLD" WHERE did = ?', (did,))
    if LAST_PIN:
        try: await c.bot.unpin_chat_message(chat_id=u.effective_chat.id, message_id=LAST_PIN)
        except: pass
    rsn = " ".join(c.args) if c.args else "Verification Under Review"
    sm = await c.bot.send_message(chat_id=u.effective_chat.id, text=f"⏳ <b>DEAL ON HOLD</b>\n🪪 <b>Deal ID:</b> {did}\n⚠️ <b>Reason:</b> {rsn}", parse_mode="HTML")
    try:
        await c.bot.pin_chat_message(chat_id=u.effective_chat.id, message_id=sm.message_id, disable_notification=True)
        LAST_PIN = sm.message_id
    except: pass

async def cmd_adminhold(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(u, c): return
    rows = db_run('SELECT did, status, amt, escrower FROM deals WHERE status IN ("ACTIVE", "ON HOLD")', fetch="all")
    if not rows: return await u.message.reply_text("🛡️ Abhi koi active hold deal nahi hai.", parse_mode="HTML")
    gtot, out = 0.0, ["🛡️ <b>ADMIN HOLD STATUS</b>\n━━━━━━━━━━━━━━━━━━━\n"]
    for r in rows:
        did, status, amt, adm = r[0], r[1], (r[2] or 0.0), (r[3] or "Admin")
        gtot += amt
        out.append(f"• <b>{did}</b> — ₹{amt:,.0f} ({status}) | Escrower: {adm}")
    out.append(f"\n💰 <b>TOTAL HOLD: ₹{gtot:,.2f}</b>")
    await u.message.reply_text("\n".join(out), parse_mode="HTML")

async def cmd_leaderboard(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not await is_owner(u, c): return
    rows = db_run('SELECT escrower, COUNT(*), COALESCE(SUM(amt), 0.0) FROM deals WHERE status = "COMPLETED" GROUP BY escrower ORDER BY SUM(amt) DESC', fetch="all")
    if not rows: return await u.message.reply_text("🏆 Abhi tak koi deal complete nahi hui hai.", parse_mode="HTML")
    out = ["🏆 <b>ESCROW ADMIN LEADERBOARD</b>\n━━━━━━━━━━━━━━━━━━━\n"]
    for idx, (adm, cnt, vol) in enumerate(rows): out.append(f"#{idx+1} <b>{adm}</b> — Deals: {cnt} | Vol: ₹{vol:,.2f}\n")
    out.append(f"━━━━━━━━━━━━━━━━━━━\n📊 <b>Total Team Volume: ₹{sum(r[2] for r in rows):,.2f}</b>")
    await u.message.reply_text("\n".join(out), parse_mode="HTML")

async def cmd_stats(u: Update, c: ContextTypes.DEFAULT_TYPE):
    row = db_run('SELECT deals, vol, fees FROM stats WHERE id = 1', fetch="one")
    await u.message.reply_text(f"📈 <b>@CHIKUESCROWSERVICE STATS</b>\n━━━━━━━━━━━━━━━━━━━\n🤝 <b>Total Deals:</b> {row[0]}\n💼 <b>Total Volume:</b> ₹{row[1]:,.2f}\n💵 <b>Total Fees:</b> ₹{row[2]:,.2f}\n📱 <b>RG :</b> @CHIKUNXT", parse_mode="HTML")

async def check_edit(u: Update, c: ContextTypes.DEFAULT_TYPE):
    em = u.edited_message
    if not em or not em.from_user or em.from_user.id == OWNER_ID: return
    try:
        await em.delete()
        await c.bot.send_message(chat_id=em.chat_id, text=f"⚠️ {em.from_user.mention_html()} <b>EDITED FORM/MESSAGE NOT ALLOWED ⚠️</b>", parse_mode="HTML")
    except: pass

async def text_router(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not u.message or not u.message.text: return
    t = u.message.text.strip().lower()
    raw = t.split('@')[0]
    cmds = {"form": cmd_form, "fee": cmd_fee, "fees": cmd_fee, "stats": cmd_stats, "leaderboard": cmd_leaderboard, "adminhold": cmd_adminhold, "refund": cmd_refund, "received": cmd_received, "recieved": cmd_received, "receive": cmd_received, "recive": cmd_received}
    if raw in cmds: await cmds[raw](u, c)
    elif raw.startswith(".") or raw.startswith("/"):
        clean_cmd = raw[1:]
        if clean_cmd in cmds: await cmds[clean_cmd](u, c)
    m = re.match(r"^(?:fee|fees|\.fee|\.fees|\/fee|\/fees)\s+([^\s]+)", t)
    if m:
        n = re.sub(r'[^\d\.]', '', m.group(1))
        if n and float(n) > 0: await send_c(u, float(n))

def main():
    threading.Thread(target=run_web, daemon=True).start()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    for name, fn in [("form", cmd_form), ("fee", cmd_fee), ("fees", cmd_fee), ("deal", cmd_deal), ("close", cmd_close), ("cancel", cmd_cancel), ("refund", cmd_refund), ("hold", cmd_hold), ("adminhold", cmd_adminhold), ("leaderboard", cmd_leaderboard), ("stats", cmd_stats)]:
        app.add_handler(CommandHandler(name, fn))
    for name in ["received", "recieved", "receive", "recive"]:
        app.add_handler(CommandHandler(name, cmd_received))
    app.add_handler(MessageHandler(filters.UpdateType.EDITED_MESSAGE, check_edit))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
    

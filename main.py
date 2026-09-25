import os, re, sqlite3, unicodedata, threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

web_app = Flask(__name__)
@web_app.route('/')
def home():
    return "Chiku Escrow Active 24/7 (SQLite Enabled)"

def run_web():
    web_app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8938665546:AAH-1KMv8sD33fEXGPGYWmLkA9ZYIxfKJ8I")
OWNER_ID = 7364435907
DB_FILE = "escrow_data.db"
LAST_PIN = None

def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS deals (
                deal_id TEXT PRIMARY KEY,
                status TEXT,
                seller TEXT,
                buyer TEXT,
                amount REAL,
                fee REAL,
                escrower TEXT,
                details TEXT,
                msg_id INTEGER
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS stats (
                id INTEGER PRIMARY KEY,
                deals INTEGER,
                vol REAL,
                fees REAL
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                val INTEGER
            )
        ''')
        c.execute('INSERT OR IGNORE INTO stats (id, deals, vol, fees) VALUES (1, 0, 0.0, 0.0)')
        c.execute('INSERT OR IGNORE INTO meta (key, val) VALUES ("deal_ctr", 11254)')
        conn.commit()

init_db()

def get_next_deal_id():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('SELECT val FROM meta WHERE key = "deal_ctr"')
        curr = c.fetchone()[0]
        nxt = curr + 1
        c.execute('UPDATE meta SET val = ? WHERE key = "deal_ctr"', (nxt,))
        conn.commit()
        return f"DL-CHIKU-{curr}"

def save_deal(did, status, seller, buyer, amt, fee, escrower, details, msg_id):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''
            INSERT OR REPLACE INTO deals (deal_id, status, seller, buyer, amount, fee, escrower, details, msg_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (did, status, seller, buyer, amt, fee, escrower, details, msg_id))
        conn.commit()

def update_deal_status(did, status):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('UPDATE deals SET status = ? WHERE deal_id = ?', (status, did))
        conn.commit()

def get_deal(did):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('SELECT status, seller, buyer, amount, fee, escrower, details, msg_id FROM deals WHERE deal_id = ?', (did,))
        row = c.fetchone()
        if row:
            return {"status": row[0], "seller": row[1], "buyer": row[2], "amount": row[3], "fee": row[4], "escrower": row[5], "details": row[6], "msg_id": row[7]}
        return None

def get_last_active_deal():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('SELECT deal_id, status, seller, buyer, amount, fee, escrower, details, msg_id FROM deals ORDER BY ROWID DESC LIMIT 1')
        row = c.fetchone()
        if row:
            return row[0], {"status": row[1], "seller": row[2], "buyer": row[3], "amount": row[4], "fee": row[5], "escrower": row[6], "details": row[7], "msg_id": row[8]}
        return None, None

def add_stats(amt, fee):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('UPDATE stats SET deals = deals + 1, vol = vol + ?, fees = fees + ? WHERE id = 1', (amt, fee))
        conn.commit()

def get_stats():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('SELECT deals, vol, fees FROM stats WHERE id = 1')
        return c.fetchone()

def get_hold_deals():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('SELECT deal_id, status, seller, buyer, amount, escrower FROM deals WHERE status IN ("ACTIVE", "ON HOLD")')
        return c.fetchall()

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
    global LAST_PIN
    if not await is_admin(u, c): return
    rep = u.message.reply_to_message
    if not rep or not (rep.text or rep.caption):
        await u.message.reply_text("⚠️ Bhare hue <b>FORM</b> ka reply karke <code>/deal</code> bhejo!", parse_mode="HTML")
        return

    if LAST_PIN:
        try: await c.bot.unpin_chat_message(chat_id=u.effective_chat.id, message_id=LAST_PIN)
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
    
    did = get_next_deal_id()
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
    
    save_deal(did, "ACTIVE", seller, buyer, amt, fee_val, (f"@{eu.username}" if eu.username else eu.first_name), dtl, sm.message_id)

async def cmd_received(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(u, c): return
    cid, rep = u.effective_chat.id, u.message.reply_to_message
    did, amt, seller, buyer = None, 0.0, "", ""

    if rep and (rep.text or rep.caption):
        f = parse_form(rep.text or rep.caption)
        did = f["id"]
        row = get_deal(did) if did else None
        amt = f["amount"] if f["amount"] > 0 else (row["amount"] if row else 0.0)
        seller = f["seller"] if f["seller"] else (row["seller"] if row else "")
        buyer = f["buyer"] if f["buyer"] else (row["buyer"] if row else "")

    if not did:
        last_did, last_row = get_last_active_deal()
        if last_did:
            did = last_did
            if amt == 0.0: amt = last_row["amount"]
            if not seller: seller = last_row["seller"]
            if not buyer: buyer = last_row["buyer"]

    did = did or "DL-CHIKU-ACTIVE"
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
    global LAST_PIN
    await del_m(u)
    if not await is_admin(u, c): return
    cid, rep = u.effective_chat.id, u.message.reply_to_message
    did, amt, seller, buyer, r_mid = None, 0.0, "", "", None

    if rep and (rep.text or rep.caption):
        r_mid = rep.message_id
        f = parse_form(rep.text or rep.caption)
        did, amt, seller, buyer = f["id"], f["amount"], f["seller"], f["buyer"]
        row = get_deal(did) if did else None
        if row:
            r_mid = row.get("msg_id", r_mid)
            if amt == 0.0: amt = row.get("amount", 0.0)
            if not seller: seller = row.get("seller", "")
            if not buyer: buyer = row.get("buyer", "")

    if not did:
        last_did, last_row = get_last_active_deal()
        if last_did:
            did = last_did
            if amt == 0.0: amt = last_row.get("amount", 0.0)
            if not seller: seller = last_row.get("seller", "")
            if not buyer: buyer = last_row.get("buyer", "")
            r_mid = last_row.get("msg_id")

    if c.args:
        n = re.sub(r'[^\d\.]', '', c.args[0])
        if n and float(n) > 0: amt = float(n)

    s_tag = seller.split()[0] if seller else "@Seller"
    b_tag = buyer.split()[0] if buyer else "@Buyer"
    did = did or "DL-CHIKU-ACTIVE"
    eu = u.effective_user

    fee_val = calc_fee(amt)[0]
    add_stats(amt, fee_val)
    if did: update_deal_status(did, "COMPLETED")

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
    last_did, _ = get_last_active_deal()
    did = last_did or "DL-CHIKU-ACTIVE"
    update_deal_status(did, "CANCELLED")
    
    if LAST_PIN:
        try: await c.bot.unpin_chat_message(chat_id=u.effective_chat.id, message_id=LAST_PIN)
        except: pass

    sm = await c.bot.send_message(chat_id=u.effective_chat.id, text=f"❌ <b>DEAL CANCELLED</b>\n🪪 <b>ID:</b> {did}\n👤 <b>By:</b> {u.effective_user.mention_html()}", parse_mode="HTML")
    try:
        await c.bot.pin_chat_message(chat_id=u.effective_chat.id, message_id=sm.message_id, disable_notification=True)
        LAST_PIN = sm.message_id
    except: pass

async def cmd_refund(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global LAST_PIN
    await del_m(u)
    if not await is_admin(u, c): return
    cid, rep = u.effective_chat.id, u.message.reply_to_message
    did, amt, buyer = None, 0.0, ""

    if rep and (rep.text or rep.caption):
        f = parse_form(rep.text or rep.caption)
        did, amt, buyer = f["id"], f["amount"], f["buyer"]
        row = get_deal(did) if did else None
        if row:
            if amt == 0.0: amt = row.get("amount", 0.0)
            if not buyer: buyer = row.get("buyer", "")

    if not did:
        last_did, last_row = get_last_active_deal()
        if last_did:
            did = last_did
            if amt == 0.0: amt = last_row.get("amount", 0.0)
            if not buyer: buyer = last_row.get("buyer", "")

    if c.args:
        n = re.sub(r'[^\d\.]', '', c.args[0])
        if n and float(n) > 0: amt = float(n)

    b_tag = buyer.split()[0] if buyer else "@Buyer"
    did = did or "DL-CHIKU-ACTIVE"
    update_deal_status(did, "REFUNDED")

    if LAST_PIN:
        try: await c.bot.unpin_chat_message(chat_id=cid, message_id=LAST_PIN)
        except: pass

    amt_lbl = f"₹{amt:,.2f}" if amt > 0 else "Deal Amount"
    txt = (
        f"🔄 <b>DEAL REFUNDED</b>\n━━━━━━━━━━━━━━━━━━━\n"
        f"🪪 <b>Trade ID:</b> {did}\n💵 <b>Refunded Amount:</b> {amt_lbl}\n"
        f"👤 <b>Refunded To:</b> {b_tag}\n👤 <b>Admin:</b> {u.effective_user.mention_html()}\n\n"
        f"🔒 <i>Deal amount has been safely refunded back to buyer.</i>"
    )
    sm = await c.bot.send_message(chat_id=cid, text=txt, parse_mode="HTML")
    try:
        await c.bot.pin_chat_message(chat_id=cid, message_id=sm.message_id, disable_notification=True)
        LAST_PIN = sm.message_id
    except: pass

async def cmd_hold(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global LAST_PIN
    await del_m(u)
    if not await is_admin(u, c): return
    last_did, _ = get_last_active_deal()
    did = last_did or "DL-CHIKU-ACTIVE"
    update_deal_status(did, "ON HOLD")
    rsn = " ".join(c.args) if c.args else "Verification / Dispute Under Review"
    
    if LAST_PIN:
        try: await c.bot.unpin_chat_message(chat_id=u.effective_chat.id, message_id=LAST_PIN)
        except: pass

    sm = await c.bot.send_message(chat_id=u.effective_chat.id, text=f"⏳ <b>DEAL ON HOLD</b>\n━━━━━━━━━━━━━━━━━━━\n🪪 <b>Deal ID:</b> {did}\n⚠️ <b>Reason:</b> {rsn}\n👤 <b>Action By:</b> {u.effective_user.mention_html()}\n\n🔒 <i>Release is paused.</i>", parse_mode="HTML")
    try:
        await c.bot.pin_chat_message(chat_id=u.effective_chat.id, message_id=sm.message_id, disable_notification=True)
        LAST_PIN = sm.message_id
    except: pass

async def cmd_adminhold(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(u, c): return
    rows = get_hold_deals()
    if not rows:
        await u.message.reply_text("🛡️ <b>ADMIN HOLD STATUS</b>\n━━━━━━━━━━━━━━━━━━━\nAbhi koi active hold deal nahi hai.", parse_mode="HTML")
        return
    ag, gtot = {}, 0.0
    for r in rows:
        did, status, seller, buyer, amt, adm = r[0], r[1], r[2], r[3], r[4], r[5]
        ag.setdefault(adm, []).append((did, amt, status))
        gtot += amt
    out = ["🛡️ <b>ADMIN HOLD STATUS</b>\n━━━━━━━━━━━━━━━━━━━\n"]
    for adm, deals in ag.items():
        total_adm = sum(d[1] for d in deals)
        out.append(f"👤 <b>{adm}</b> — Hold: ₹{total_adm:,.2f}")
        for did, amt, status in deals:
            _, rate, _, net = calc_fee(amt)
            out.append(f"  • <b>{did}</b> — ₹{amt:,.0f} ({status})\n    Fee: {rate} | Net: ₹{net:,.0f}")
        out.append("")
    out.append("────────────────

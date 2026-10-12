import os, re, unicodedata, threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

web_app = Flask(__name__)
@web_app.route('/')
def home():
    return "Chiku Escrow Active 24/7"

def run_web():
    web_app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8938665546:AAHnBE3UDHwj501WbSNF0ZeKq0dnVqz7TZM")
OWNER_ID = 7364435907
DEALS_DB = {}
STATS = {"deals": 0, "vol": 0.0, "fees": 0.0}
DEAL_CTR, CURR_DEAL, LAST_PIN = 11254, None, None
ADMINS_LIST = {OWNER_ID}
CO_OWNERS = set()

async def is_admin(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not u.effective_user: return False
    uid = u.effective_user.id
    if uid == OWNER_ID or uid in CO_OWNERS or uid in ADMINS_LIST or u.effective_chat.type == "private":
        return True
    try:
        admins = await c.bot.get_chat_administrators(u.effective_chat.id)
        return any(a.user.id == uid for a in admins)
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
    if amt <= 100: return 10.0, "Flat ₹10", "Rs 10", amt - 10.0
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

async def safe_pin(c, cid, mid):
    try:
        await c.bot.pin_chat_message(chat_id=cid, message_id=mid, disable_notification=True)
    except:
        pass

async def cmd_start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    uid = u.effective_user.id if u.effective_user else 0
    if uid == OWNER_ID and u.effective_chat.type == "private":
        await u.message.reply_text(
            "🛡️ <b>CHIKU ESCROW — OWNER CONTROL PANEL</b>\n\n"
            "👋 Welcome Harshal! Aap yahan se bot ko manage aur configure kar sakte hain.\n\n"
            "⚙️ <b>Quick Admin Commands:</b>\n"
            "• /help - All commands list\n"
            "• /stats - Business overview\n"
            "• /admins - Manage admins\n"
            "• /settings - Bot preferences",
            parse_mode="HTML"
        )
    else:
        msg = (
            "🛡️ <b>CHIKU ESCROW</b>\n\n"
            "👋 Welcome to Chiku Escrow!\n\n"
            "🔐 Secure Escrow Service\n"
            "💰 Transparent Fee System\n"
            "🤝 Safe Deal Management\n\n"
            "If you need escrow assistance, please contact @HARSHALxNXT."
        )
        await u.message.reply_text(msg, parse_mode="HTML")

async def cmd_help(u: Update, c: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🛡️ <b>CHIKU ESCROW — ADMIN COMMANDS</b>\n\n"
        "/deal 500 — Add escrow deal\n"
        "/close — Close your own deal\n"
        "/hold Reason — Hold your own deal\n"
        "/unhold — Remove hold\n"
        "/cancel — Cancel your own deal\n"
        "/refund — Refund your own deal\n"
        "/c 500 — 💎 Public Fee Calculator\n\n"
        "/settradeid 198 — Owner / Co-Owner only\n"
        "/minus — Remove latest deal\n"
        "/stats — GC deal statistics\n"
        "/earnings — Earnings\n"
        "/report — Deal report\n\n"
        "/admins — Access list\n"
        "/addadmin ID — Add one admin\n"
        "/removeadmin ID — Remove admin\n\n"
        "/coowneradd ID — Owner only\n"
        "/coownerremove ID — Owner only\n"
        "/coowners — Co-owner list\n\n"
        "/settings — Bot settings\n"
        "/fee — Universal fee settings\n"
        "/chatid — Chat ID\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "💰 <b>UNIVERSAL FEE SYSTEM</b>\n\n"
        "₹1–₹100 — ₹10\n"
        "₹101–₹599 — ₹20\n"
        "₹600–₹2000 — 3.5%\n"
        "₹2001+ — 3%\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "⚖️ <b>DEAL RULES</b>\n"
        "🔒 Only original escrower can close.\n"
        "⚠️ Only original escrower can hold.\n"
        "🔓 Only original escrower can unhold.\n"
        "❌ Only original escrower can cancel.\n"
        "🔄 Only original escrower can refund.\n"
        "🪪 Only Owner / Co-Owner can set Trade ID."
    )
    await u.message.reply_text(msg, parse_mode="HTML")

async def cmd_c(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not c.args:
        await u.message.reply_text("💡 Use: <code>/c 500</code>", parse_mode="HTML")
        return
    num = re.sub(r'[^\d\.]', '', c.args[0])
    if num and float(num) > 0:
        amt = float(num)
        fee, rate, _, rcv = calc_fee(amt)
        await u.message.reply_text(f"💎 <b>Public Fee Calculator</b>\nAmount: ₹{amt:,.0f}\nFee: ₹{fee:,.0f} ({rate})\nTotal / Net: ₹{rcv:,.0f}", parse_mode="HTML")

async def cmd_settradeid(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global DEAL_CTR
    uid = u.effective_user.id if u.effective_user else 0
    if uid != OWNER_ID and uid not in CO_OWNERS:
        return await u.message.reply_text("⚠️ Owner / Co-Owner only command!")
    if c.args and c.args[0].isdigit():
        DEAL_CTR = int(c.args[0])
        await u.message.reply_text(f"✅ Trade ID counter set to: DL-CHIKU-{DEAL_CTR}")
    else:
        await u.message.reply_text("💡 Use: <code>/settradeid 198</code>", parse_mode="HTML")

async def cmd_minus(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(u, c): return
    if DEALS_DB:
        last_key = list(DEALS_DB.keys())[-1]
        del DEALS_DB[last_key]
        await u.message.reply_text(f"🗑️ Latest deal record ({last_key}) removed successfully.")
    else:
        await u.message.reply_text("⚠️ No active deals to remove.")

async def cmd_unhold(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global LAST_PIN
    await del_m(u)
    if not await is_admin(u, c): return
    if CURR_DEAL in DEALS_DB: DEALS_DB[CURR_DEAL]["status"] = "ACTIVE"
    if LAST_PIN:
        try: await c.bot.unpin_chat_message(chat_id=u.effective_chat.id, message_id=LAST_PIN)
        except: pass
    sm = await c.bot.send_message(chat_id=u.effective_chat.id, text=f"🔓 <b>DEAL UNHOLD / RESUMED</b>\n🪪 <b>ID:</b> {CURR_DEAL or 'DL-ACTIVE'}", parse_mode="HTML")
    await safe_pin(c, u.effective_chat.id, sm.message_id)
    LAST_PIN = sm.message_id

async def cmd_earnings(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(u, c): return
    await u.message.reply_text(f"📊 <b>Total Earnings / Fees:</b> ₹{STATS['fees']:,.2f}", parse_mode="HTML")

async def cmd_report(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(u, c): return
    await u.message.reply_text(f"📋 <b>Deal Report Summary:</b>\nTotal Deals: {STATS['deals']}\nVolume: ₹{STATS['vol']:,.2f}\nFees: ₹{STATS['fees']:,.2f}", parse_mode="HTML")

async def cmd_coowneradd(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not u.effective_user or u.effective_user.id != OWNER_ID:
        return await u.message.reply_text("⚠️ Owner only command!")
    if c.args and c.args[0].isdigit():
        uid = int(c.args[0])
        CO_OWNERS.add(uid)
        await u.message.reply_text(f"✅ Co-Owner ID {uid} added.")
    else:
        await u.message.reply_text("💡 Use: <code>/coowneradd 123456789</code>", parse_mode="HTML")

async def cmd_coownerremove(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not u.effective_user or u.effective_user.id != OWNER_ID:
        return await u.message.reply_text("⚠️ Owner only command!")
    if c.args and c.args[0].isdigit():
        uid = int(c.args[0])
        if uid in CO_OWNERS: CO_OWNERS.remove(uid)
        await u.message.reply_text(f"✅ Co-Owner ID {uid} removed.")
    else:
        await u.message.reply_text("💡 Use: <code>/coownerremove 123456789</code>", parse_mode="HTML")

async def cmd_coowners(u: Update, c: ContextTypes.DEFAULT_TYPE):
    lst = ", ".join(str(i) for i in CO_OWNERS) if CO_OWNERS else "None"
    await u.message.reply_text(f"👑 <b>Co-Owners List:</b>\n<code>{lst}</code>", parse_mode="HTML")

async def cmd_settings(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(u, c): return
    await u.message.reply_text("⚙️ <b>Bot Settings Panel:</b>\nAll systems are fully functional and secure under @HARSHALxNXT.", parse_mode="HTML")

async def cmd_fee(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text("💰 <b>Universal Fee System:</b>\n₹1–₹100 — ₹10\n₹101–₹599 — ₹20\n₹600–₹2000 — 3.5%\n₹2001+ — 3%", parse_mode="HTML")

async def cmd_addadmin(u: Update, c: ContextTypes.DEFAULT_TYPE):
    uid = u.effective_user.id if u.effective_user else 0
    if uid != OWNER_ID and uid not in CO_OWNERS:
        return await u.message.reply_text("⚠️ Owner / Co-Owner only command!")
    if c.args:
        for arg in c.args:
            if arg.isdigit():
                ADMINS_LIST.add(int(arg))
        await u.message.reply_text("✅ Admin(s) added successfully.")
    else:
        await u.message.reply_text("💡 Use: <code>/addadmin ID1 ID2</code>", parse_mode="HTML")

async def cmd_removeadmin(u: Update, c: ContextTypes.DEFAULT_TYPE):
    uid = u.effective_user.id if u.effective_user else 0
    if uid != OWNER_ID and uid not in CO_OWNERS:
        return await u.message.reply_text("⚠️ Owner / Co-Owner only command!")
    if c.args and c.args[0].isdigit():
        uid_to_rem = int(c.args[0])
        if uid_to_rem in ADMINS_LIST: ADMINS_LIST.remove(uid_to_rem)
        await u.message.reply_text(f"✅ Admin ID {uid_to_rem} removed.")
    else:
        await u.message.reply_text("💡 Use: <code>/removeadmin 123456789</code>", parse_mode="HTML")

async def cmd_admins(u: Update, c: ContextTypes.DEFAULT_TYPE):
    lst = ", ".join(str(i) for i in ADMINS_LIST)
    await u.message.reply_text(f"🛡️ <b>Authorized Admins ID:</b>\n<code>{lst}</code>", parse_mode="HTML")

async def cmd_chatid(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(f"💬 <b>Chat ID:</b> <code>{u.effective_chat.id}</code>", parse_mode="HTML")

async def cmd_deal(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global DEAL_CTR, CURR_DEAL, LAST_PIN
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
    _, _, fee_tag, _ = calc_fee(amt)
    fee_line = f"\n\nFees {fee_tag}" if amt > 0 else ""
    did = f"DL-CHIKU-{DEAL_CTR}"
    DEAL_CTR += 1
    CURR_DEAL = did
    eu = u.effective_user
    amt_lbl = f"₹{amt:,.0f}" if amt > 0 else "Deal Amount"
    dtl = f['details'] if f['details'] else 'N/A'
    till = f['till'] if f['till'] else 'SECURE'
    msg = f"<b>ESCROW DEAL</b>\n🪪 <b>DEAL ID:</b> {did}\n\n• <b>ꜱᴇʟʟᴇʀ :</b> {seller}\n• <b>ʙᴜʏᴇʀ  :</b> {buyer}\n\n• <b>ᴅᴇᴀʟ ᴅᴇᴀᴛᴀɪʟꜱ :</b> {dtl}\n• <b>ᴅᴇᴀʟ ᴀᴍᴏᴜɴᴛ :</b> {amt_lbl}\n• <b>ᴇꜱᴄʀᴏᴡ ᴛɪʟʟ :</b> {till}\n\n<b>Escrower :</b> {eu.mention_html()} ({eu.id}){fee_line}"
    sm = await c.bot.send_message(chat_id=u.effective_chat.id, text=msg, parse_mode="HTML")
    await safe_pin(c, u.effective_chat.id, sm.message_id)
    LAST_PIN = sm.message_id
    DEALS_DB[did] = {"status": "ACTIVE", "seller": seller, "buyer": buyer, "amount": amt, "escrower": eu.id, "details": dtl, "msg_id": sm.message_id}

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
    msg = f"💰 <b>PAYMENT RECEIVED & CONFIRMED!</b>\n━━━━━━━━━━━━━━━━━━━\n🪪 <b>Deal ID:</b> {did}\n💵 <b>Amount:</b> {amt_lbl}\n👤 <b>Buyer:</b> {b_tag}\n👤 <b>Seller:</b> {s_tag}\n━━━━━━━━━━━━━━━━━━━\n\n🤝 <b>TRANSFER ACCESS TO BUYER WITH SCREENRECORDS !!</b> 🤝\n\n⚠️ <i>Seller video record karke access transfer karein aur Buyer verify karke vouch karein.</i>"
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
    txt = f"✅ <b>Deal Completed</b>\n🪪 <b>Trade ID:</b>\n{did}\n📤 <b>Released:</b> {amt_lbl}\n👤 <b>Escrowed By:</b>\n{esc_by}\n\n~ {b_tag} and {s_tag}\nare requested to drop the\nvouch before leaving 👇🏻\n\n<code>Vouch @chikuescrowservice for {amt_lbl} smooth escrow deal</code>"
    sm = await c.bot.send_message(chat_id=cid, text=txt, parse_mode="HTML")
    await safe_pin(c, cid, sm.message_id)
    LAST_PIN = sm.message_id

async def cmd_cancel(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global LAST_PIN
    await del_m(u)
    if not await is_admin(u, c): return
    did = CURR_DEAL or f"DL-CHIKU-{DEAL_CTR}"
    if did in DEALS_DB: DEALS_DB[did]["status"] = "CANCELLED"
    if LAST_PIN:
        try: await c.bot.unpin_chat_message(chat_id=u.effective_chat.id, message_id=LAST_PIN)
        except: pass
    sm = await c.bot.send_message(chat_id=u.effective_chat.id, text=f"❌ <b>DEAL CANCELLED</b>\n🪪 <b>ID:</b> {did}\n👤 <b>By:</b> {u.effective_user.mention_html()}", parse_mode="HTML")
    await safe_pin(c, u.effective_chat.id, sm.message_id)
    LAST_PIN = sm.message_id

async def cmd_refund(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global LAST_PIN
    await del_m(u)
    if not await is_admin(u, c): return
    cid, rep = u.effective_chat.id, u.message.reply_to_message
    did, amt, buyer = None, 0.0, ""
    if rep and (rep.text or rep.caption):
        f = parse_form(rep.text or rep.caption)
        did, amt, buyer = f["id"], f["amount"], f["buyer"]
        if did and did in DEALS_DB:
            if amt == 0.0: amt = DEALS_DB[did].get("amount", 0.0)
        

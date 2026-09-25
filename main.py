import os, re, unicodedata, threading, asyncio
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
OWNER_ID, PROOF_CHANNEL = 7364435907, ""
DEALS_DB, STATS = {}, {"total_deals": 0, "total_volume": 0.0, "total_fees": 0.0}
DEAL_COUNTER, LATEST_ACTIVE_DEAL, LATEST_PINNED_MSG_ID = 1, None, None

async def is_admin(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if u.effective_user.id == OWNER_ID: 
        return True
    try: 
        return any(a.user.id == u.effective_user.id for a in await c.bot.get_chat_administrators(u.effective_chat.id))
    except: 
        return False

def norm_txt(t):
    if not t: 
        return ""
    norm = unicodedata.normalize('NFKD', str(t))
    conv = {
        'ꜱ':'s','s':'s','ᴇ':'e','e':'e','ʟ':'l','l':'l','ʀ':'r','r':'r',
        'ʙ':'b','b':'b','ᴜ':'u','u':'u','ʏ':'y','y':'y','ᴅ':'d','d':'d',
        'ᴀ':'a','a':'a','ᴛ':'t','t':'t','ɪ':'i','i':'i','ᴏ':'o','o':'o',
        'ᴡ':'w','w':'w','м':'m','m':'m','ɴ':'n','n':'n','ᴄ':'c','c':'c',
        'ʜ':'h','h':'h','ᴋ':'k','k':'k','ᴘ':'p','p':'p','ғ':'f','f':'f'
    }
    return "".join(conv.get(ch, ch) for ch in norm)

def get_fee(amt):
    if amt <= 0: 
        return 0.0, "0%", "0₹", 0.0
    if amt <= 190: 
        return 10.0, "Flat ₹10", "Rs 10", amt - 10.0
    if amt <= 599: 
        return 20.0, "Flat ₹20", "Rs 20", amt - 20.0
    if amt <= 2000: 
        return round(amt*0.035, 2), "3.5%", f"3.5% - {round(amt*0.035):,.0f}₹", amt - round(amt*0.035, 2)
    return round(amt*0.03, 2), "3%", f"3% - {round(amt*0.03):,.0f}₹", amt - round(amt*0.03, 2)

def parse_amt(val):
    if not val: 
        return 0.0
    val_clean = str(val).lower().replace("₹", "").replace(",", "").replace("rs", "").replace("inr", "")
    m = re.search(r"(\d+(?:\.\d+)?)(\s*k)?", val_clean)
    if m:
        num = float(m.group(1))
        return num * (1000 if m.group(2) else 1)
    return 0.0

def extract_f(raw):
    n = norm_txt(raw)
    f = {"seller": "", "buyer": "", "details": "", "amount": "", "till": "", "upi": "", "deal_id": ""}
    dm = re.search(r"DL[-_ ]*CHIKU[-_ ]*\d+", n, re.I)
    if dm: 
        f["deal_id"] = re.sub(r"\s+", "", dm.group(0).upper().replace("_", "-"))
    patterns = {
        "seller": r"(?:[•\*\-]?\s*seller|sell(?:er)?)\s*[:\-]\s*([^\n\r]+)",
        "buyer": r"(?:[•\*\-]?\s*buyer|buy(?:er)?)\s*[:\-]\s*([^\n\r]+)",
        "details": r"(?:[•\*\-]?\s*(?:deal\s*)?(?:deatails|details|detail|info))\s*[:\-]\s*([^\n\r]+)",
        "amount": r"(?:[•\*\-]?\s*(?:deal\s*)?(?:amount|amt|price|cost|released))\s*[:\-]\s*([^\n\r]+)",
        "till": r"(?:[•\*\-]?\s*(?:escrow\s*)?till)\s*[:\-]\s*([^\n\r]+)",
        "upi": r"(?:[•\*\-]?\s*(?:for\s*release\s*)?(?:seller\s*)?upi)\s*[:\-]\s*([^\n\r]+)"
    }
    for key, p in patterns.items():
        m = re.search(p, n, re.I)
        if m: 
            f[key] = m.group(1).strip()
    return f

async def res_uid(u, rep, ctx, cid):
    if not u or u.upper() == "N/A": 
        return u or "N/A"
    cln = u.strip()
    if "(" in cln and ")" in cln: 
        return cln
    if cln.isdigit(): 
        return f'<a href="tg://user?id={cln}">{cln}</a> ({cln})'
    if cln.lower() in ["me", "i", "myself", "mai", "main", "admin"] and rep and rep.from_user:
        fu = rep.from_user
        tag = f"@{fu.username}" if fu.username else fu.first_name
        return f"{tag} ({fu.id})"
    if rep and rep.entities:
        for ent in rep.entities:
            if ent.type == "text_mention" and ent.user:
                mt = rep.text[ent.offset:ent.offset+ent.length] if rep.text else ""
                if (cln.lower() in mt.lower()) or (ent.user.first_name and cln.lower() in ent.user.first_name.lower()):
                    return f'{ent.user.mention_html()} ({ent.user.id})'
    if rep and rep.from_user:
        fu = rep.from_user
        if (fu.first_name and cln.lower() in fu.first_name.lower()) or (fu.username and cln.replace("@","").lower() == fu.username.lower()):
            return f'{fu.mention_html()} ({fu.id})'
    pure_u = cln.replace("@", "")
    if cln.startswith("@"):
        try:
            m = await ctx.bot.get_chat_member(cid, f"@{pure_u}")
            if m and m.user: 
                return f"@{pure_u} ({m.user.id})"
        except: 
            pass
        return f"@{pure_u}"
    return cln

async def safe_del(u: Update):
    try:
        if u.message: 
            await u.message.delete()
    except: 
        pass

async def unpin_old(c: ContextTypes.DEFAULT_TYPE, cid, mid=None):
    global LATEST_PINNED_MSG_ID
    tgt = mid or LATEST_PINNED_MSG_ID
    if tgt:
        try: 
            await c.bot.unpin_chat_message(chat_id=cid, message_id=tgt)
        except: 
            pass

async def send_fee_result(u: Update, amt: float):
    f, r, _, rcv = get_fee(amt)
    await u.message.reply_text(
        f"📊 <b>@CHIKUESCROWSERVICE FEE CALCULATOR</b>\n━━━━━━━━━━━━━━━━━━━\n💰 <b>Deal Amount:</b> ₹{amt:,.0f}\n⚡ <b>Fee Rate:</b> {r}\n💵 <b>Escrow Fee:</b> ₹{f:,.0f}\n━━━━━━━━━━━━━━━━━━━\n✅ <b>Seller Receives:</b> ₹{rcv:,.0f}\n\n📱 <b>RG :</b> @CHIKUNXT",
        parse_mode="HTML"
    )

async def form(u: Update, c: ContextTypes.DEFAULT_TYPE):
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

async def fee_command(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not c.args:
        await u.message.reply_text(
            "<b>@CHIKUESCROWSERVICE CHARGES -</b>\n\n• Under ₹190 - ₹10\n• ₹191 To ₹599 - ₹20\n• ₹600 To ₹2000 - 3.5%\n• ₹2001 To ₹3000 - 3%\n• Upper Than ₹3000 - 3%\n\n📱 <b>RG :</b> @CHIKUNXT\n━━━━━━━━━━━━━━━━━━━\n💡 Check amount: <code>fees 2000</code>",
            parse_mode="HTML"
        )
        return
    amt = parse_amt(c.args[0])
    if amt > 0: 
        await send_fee_result(u, amt)

async def start_deal(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global DEAL_COUNTER, LATEST_ACTIVE_DEAL, LATEST_PINNED_MSG_ID
    if not await is_admin(u, c): 
        return
    rep = u.message.reply_to_message
    if not rep or not (rep.text or rep.caption):
        await u.message.reply_text("⚠️ Bhare hue <b>FORM</b> ka <b>Reply</b> karke <code>/deal</code> likhein!", parse_mode="HTML")
        return
    try: 
        await c.bot.unpin_chat_message(chat_id=u.effective_chat.id, message_id=rep.message_id)
    except: 
        pass
    f = extract_f(rep.text or rep.caption)
    s_fmt = await res_uid(f["seller"] or "N/A", rep, c, u.effective_chat.id)
    b_fmt = await res_uid(f["buyer"] or "N/A", rep, c, u.effective_chat.id)
    amt_num = parse_amt(f["amount"])
    fee_num, fee_line = (get_fee(amt_num)[0], f"\n\nFees {get_fee(amt_num)[2]}") if amt_num > 0 else (0.0, "")
    did = f"DL-CHIKU-{DEAL_COUNTER:02d}"
    DEAL_COUNTER += 1
    LATEST_ACTIVE_DEAL = did
    eu = u.effective_user
    amt_display = f"₹{amt_num:,.0f}" if amt_num > 0 else (f['amount'] or 'N/A')
    till = f['till'] if f['till'] else "SECURE"
    details = f['details'] if f['details'] else 'N/A'
    
    sm = await c.bot.send_message(
        chat_id=u.effective_chat.id,
        text=f"<b>ESCROW DEAL</b>\n🪪 <b>DEAL ID:</b> {did}\n\n• <b>ꜱᴇʟʟᴇʀ :</b> {s_fmt}\n• <b>ʙᴜʏᴇʀ  :</b> {b_fmt}\n\n• <b>ᴅᴇᴀʟ ᴅᴇᴀᴛᴀɪʟꜱ :</b> {details}\n• <b>ᴅᴇᴀʟ ᴀᴍᴏᴜɴᴛ :</b> {amt_display}\n• <b>ᴇꜱᴄʀᴏᴡ ᴛɪʟʟ :</b> {till}\n\n<b>Escrower :</b> {eu.mention_html()} ({eu.id}){fee_line}",
        parse_mode="HTML"
    )
    try:
        await c.bot.pin_chat_message(chat_id=u.effective_chat.id, message_id=sm.message_id, disable_notification=True)
        LATEST_PINNED_MSG_ID = sm.message_id
    except: 
        pass
    DEALS_DB[did] = {"status": "ACTIVE", "seller": s_fmt, "buyer": b_fmt, "amount": amt_num, "fee": fee_num, "escrower": (f"@{eu.username}" if eu.username else eu.first_name), "details": details, "msg_id": sm.message_id}

async def close_deal(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global DEAL_COUNTER, LATEST_ACTIVE_DEAL, LATEST_PINNED_MSG_ID
    await safe_del(u)
    if not await is_admin(u, c): 
        return
    cid, rep, did, amt_str, buyer, seller, rep_mid = u.effective_chat.id, u.message.reply_to_message, None, "", "", "", None
    if rep and (rep.text or rep.caption):
        rep_mid, f = rep.message_id, extract_f(rep.text or rep.caption)
        did = f["deal_id"]
        if did and did in DEALS_DB:
            amt_str = str(DEALS_DB[did]["amount"])
            seller, buyer = DEALS_DB[did]["seller"], DEALS_DB[did]["buyer"]
            rep_mid = DEALS_DB[did].get("msg_id", rep_mid)
        else:
            amt_str, seller, buyer = f["amount"], f["seller"], f["buyer"]
    if not did and LATEST_ACTIVE_DEAL and LATEST_ACTIVE_DEAL in DEALS_DB:
        did = LATEST_ACTIVE_DEAL
        amt_str = str(DEALS_DB[did]["amount"])
        seller, buyer = DEALS_DB[did]["seller"], DEALS_DB[did]["buyer"]
        rep_mid = DEALS_DB[did].get("msg_id")
    if len(c.args) >= 1 and not amt_str: 
        amt_str = c.args[0]
    if len(c.args) >= 2 and not buyer: 
        buyer = c.args[1]
    if len(c.args) >= 3 and not seller: 
        seller = c.args[2]
    
    amt_num = parse_amt(amt_str)
    seller_tag = seller.split()[0] if seller else "@Seller"
    buyer_tag = buyer.split()[0] if buyer else "@Buyer"
    eu = u.effective_user
    if not did:
        did = f"DL-CHIKU-{DEAL_COUNTER:02d}"
        DEAL_COUNTER += 1
    STATS["total_deals"] += 1
    STATS["total_volume"] += amt_num
    STATS["total_fees"] += get_fee(amt_num)[0]
    DEALS_DB[did] = {"status": "COMPLETED", "seller": seller, "buyer": buyer, "amount": amt_num, "fee": get_fee(amt_num)[0], "escrower": (f"@{eu.username}" if eu.username else eu.mention_html()), "details": "Completed Deal"}
    LATEST_ACTIVE_DEAL = did
    await unpin_old(c, cid, rep_mid)
    amt_disp = f"₹{amt_num:,.2f}" if amt_num > 0 else "Deal Amount"
    sm = await c.bot.send_message(
        chat_id=cid,
        text=f"✅ <b>Deal Completed</b>\n🪪 <b>Trade ID:</b>\n{did}\n📤 <b>Released:</b> {amt_disp}\n👤 <b>Escrowed By:</b>\n{f'@{eu.username}' if eu.username else eu.mention_html()}\n\n~ {buyer_tag} and {seller_tag}\nare requested to drop the\nvouch before leaving 👇🏻\n\n<code>Vouch @chikuescrowservice for {amt_disp} smooth escrow deal</code>",
        parse_mode="HTML"
    )
    try:
        await c.bot.pin_chat_message(chat_id=cid, message_id=sm.message_id, disable_notification=True)
        LATEST_PINNED_MSG_ID = sm.message_id
    except: 
        pass
    if PROOF_CHANNEL:
        try: 
            await c.bot.send_message(chat_id=PROOF_CHANNEL, text=sm.text, parse_mode="HTML")
        except: 
            pass

async def hold_deal(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global LATEST_ACTIVE_DEAL, LATEST_PINNED_MSG_ID
    await safe_del(u)
    if not await is_admin(u, c): 
        return
    cid, rep = u.effective_chat.id, u.message.reply_to_message
    rep_mid = rep.message_id if rep else None
    did = (extract_f(rep.text or rep.caption).get("deal_id") if rep and (rep.text or rep.caption) else None) or LATEST_ACTIVE_DEAL or "UNKNOWN"
    if did in DEALS_DB:
        DEALS_DB[did]["status"] = "ON HOLD"
        rep_mid = DEALS_DB[did].get("msg_id", rep_mid)
    await unpin_old(c, cid, rep_mid)
    rsn = " ".join(c.args) if c.args else "Verification / Dispute Under Review"
    sm = await c.bot.send_message(
        chat_id=cid,
        text=f"⏳ <b>DEAL ON HOLD</b>\n━━━━━━━━━━━━━━━━━━━\n🪪 <b>Deal ID:</b> {did}\n⚠️ <b>Reason:</b> {rsn}\n👤 <b>Action By:</b> {u.effective_user.mention_html()}\n\n🔒 <i>Payment release is paused until further update.</i>",
        parse_mode="HTML"
    )
    try:
        await c.bot.pin_chat_message(chat_id=cid, message_id=sm.message_id, disable_notification=True)
        LATEST_PINNED_MSG_ID = sm.message_id
    except: 
        pass

async def cancel_deal(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global LATEST_ACTIVE_DEAL, LATEST_PINNED_MSG_ID
    await safe_del(u)
    if not await is_admin(u, c): 
        return
    cid, rep = u.effective_chat.id, u.message.reply_to_message
    rep_mid = rep.message_id if rep else None
    f = extract_f(rep.text or rep.caption) if rep and (rep.text or rep.caption) else {}
    did = f.get("deal_id") or LATEST_ACTIVE_DEAL or "UNKNOWN"
    seller, buyer, amt_str = f.get("seller", ""), f.get("buyer", ""), f.get("amount", "")
    if did in DEALS_DB:
        DEALS_DB[did]["status"] = "CANCELLED"
        seller, buyer, amt_str = DEALS_DB[did]["seller"], DEALS_DB[did]["buyer"], str(DEALS_DB[did]["amount"])
        rep_mid = DEALS_DB[did].get("msg_id", rep_mid)
    await unpin_old(c, cid, rep_mid)
    amt_num = parse_amt(amt_str)
    sm = await c.bot.send_message(
        chat_id=cid,
        text=f"❌ <b>DEAL CANCELLED</b>\n━━━━━━━━━━━━━━━━━━━\n🪪 <b>Deal ID:</b> {did}\n💰 <b>Amount:</b> {f'₹{amt_num:,.0f}' if amt_num > 0 else 'N/A'}\n👤 <b>Seller:</b> {seller.split()[0] if seller else '@Seller'}\n👤 <b>Buyer:</b> {buyer.split()[0] if buyer else '@Buyer'}\n⚠️ <b>Reason:</b> {' '.join(c.args) if c.args else 'Mutual Agreement'}\n👤 <b>Action By:</b> {u.effective_user.mention_html()}",
        parse_mode="HTML"
    )
    try:
        await c.bot.pin_chat_message(chat_id=cid, message_id=sm.message_id, disable_notification=True)
        LATEST_PINNED_MSG_ID = sm.message_id
    except: 
        pass
    if LATEST_ACTIVE_DEAL == did: 
        LATEST_ACTIVE_DEAL = None

async def refund_deal(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global LATEST_ACTIVE_DEAL, LATEST_PINNED_MSG_ID
    await safe_del(u)
    if not await is_admin(u, c): 
        return
    cid, rep = u.effective_chat.id, u.message.reply_to_message
    rep_mid = rep.message_id if rep else None
    f = extract_f(rep.text or rep.caption) if rep and (rep.text or rep.caption) else {}
    did = f.get("deal_id") or LATEST_ACTIVE_DEAL or "N/A"
    buyer, amt_str = f.get("buyer", ""), f.get("amount", "")
    if did in DEALS_DB:
        DEALS_DB[did]["status"] = "REFUNDED"
        buyer, amt_str = DEALS_DB[did]["buyer"], str(DEALS_DB[did]["amount"])
        rep_mid = DEALS_DB[did].get("msg_id", rep_mid)
    await unpin_old(c, cid, rep_mid)
    amt_num = parse_amt(amt_str)
    sm = await c.bot.send_message(
        chat_id=cid,
        text=f"↩️ <b>ESCROW REFUND PROCESSED</b>\n━━━━━━━━━━━━━━━━━━━\n🪪 <b>Deal ID:</b> {did}\n👤 <b>Refund To:</b> {buyer.split()[0] if buyer else '@Buyer'}\n💰 <b>Amount:</b> {f'₹{amt_num:,.0f}' if amt_num > 0 else 'Deal Amount'}\n👤 <b>Escrower:</b> {u.effective_user.mention_html()}\n\n⚠️ <i>Escrow fees non-refundable as per policy.</i>",
        parse_mode="HTML"
    )
    try:
        await c.bot.pin_chat_message(chat_id=cid, message_id=sm.message_id, disable_notification=True)
        LATEST_PINNED_MSG_ID = sm.message_id
    except: 
        pass
    if LATEST_ACTIVE_DEAL == did: 
        LATEST_ACTIVE_DEAL = None

async def status_deal(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global LATEST_ACTIVE_DEAL
    rep = u.message.reply_to_message
    raw_rep = rep.text or rep.caption if rep else ""
    did = extract_f(raw_rep).get("deal_id") if raw_rep else None
    if not did and c.args: 
        did = extract_f(" ".join(c.args)).get("deal_id") or re.sub(r"\s+", "", " ".join(c.args).upper().replace("_", "-"))
    if not did and LATEST_ACTIVE_DEAL: 
        did = LATEST_ACTIVE_DEAL
    if not did: 
        await u.message.reply_text("⚠️ Deal slip par <b>Reply</b> karke <code>/status</code> likhein!", parse_mode="HTML")
        return
    
    if did in DEALS_DB:
        d = DEALS_DB[did]
        amt_disp = f"₹{d.get('amount', 0.0):,.0f}" if d.get('amount', 0.0) > 0 else "Deal Amount"
        bdg = {"ACTIVE": "🟢", "COMPLETED": "✅", "CANCELLED": "❌", "ON HOLD": "⏳", "REFUNDED": "↩️"}.get(d["status"], "📌")
        await u.message.reply_text(f"🔍 <b>DEAL STATUS</b>\n🪪 <b>ID:</b> {did}\n📌 <b>Status:</b> {bdg} {d['status']}\n💰 <b>Amount:</b> {amt_disp}\n👤 <b>Seller:</b> {d.get('seller','N/A')}\n👤 <b>Buyer:</b> {d.get('buyer','N/A')}", parse_mode="HTML")
        return
    if raw_rep:
        f = extract_f(raw_rep)
        st = ("COMPLETED" if "completed" in raw_rep.lower() else ("ON HOLD" if "hold" in raw_rep.lower() else ("CANCELLED" if "cancelled" in raw_rep.lower() else "ACTIVE")))
        bdg = {"ACTIVE": "🟢", "COMPLETED": "✅", "CANCELLED": "❌", "ON HOLD": "⏳"}.get(st, "📌")
        val = parse_amt(f["amount"])
        await u.message.reply_text(f"🔍 <b>DEAL STATUS</b>\n🪪 <b>ID:</b> {did}\n📌 <b>Status:</b> {bdg} {st}\n💰 <b>Amount:</b> {f'₹{val:,.0f}' if val > 0 else (f['amount'] or 'Deal Amount')}\n👤 <b>Seller:</b> {f['seller'] or 'N/A'}\n👤 <b>Buyer:</b> {f['buyer'] or 'N/A'}", parse_mode="HTML")
        return
    await u.message.reply_text(f"❓ Deal ID <code>{did}</code> record me nahi mili.", parse_mode="HTML")

async def stats_cmd(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(f"📈 <b>@CHIKUESCROWSERVICE STATS</b>\n━━━━━━━━━━━━━━━━━━━\n🤝 <b>Total Deals:</b> {STATS['total_deals']}\n💼 <b>Total Volume:</b> ₹{STATS['total_volume']:,.2f}\n💵 <b>Total Fees:</b> ₹{STATS['total_fees']:,.2f}", parse_mode="HTML")

async def admin_hold_cmd(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if u.effective_user.id != OWNER_ID: 
        return
    hd = {k: v for k, v in DEALS_DB.items() if v["status"] in ["ACTIVE", "ON HOLD"]}
    if not hd: 
        await u.message.reply_text("🛡️ <b>ADMIN HOLD</b>\n\nAbhi koi active hold deal nahi hai.", parse_mode="HTML")
        return
    ag, gtot = {}, 0.0
    for did, info in hd.items():
        ag.setdefault(info.get("escrower", "Unknown Escrower"), []).append((did, info))
        gtot += info["amount"]
    out = ["🛡️ <b>ADMIN HOLD</b>\n"]
    for adm, deals in ag.items():
        out.append(f"🛡️ <b>{adm}</b> — Total Hold: ₹{sum(d[1]['amount'] for d in deals):,.2f}")
        for did, d in deals:
            _, rate, _, net = get_fee(d["amount"])
            out.append(f"  • <b>{did}</b> — ₹{d['amount']:,.2f}\n    Buyer: {d['buyer'].split()[0] if d['buyer'] else '@Buyer'} | Seller: {d['seller'].split()[0] if d['seller'] else '@Seller'}\n    Fee: {rate} — Net: ₹{net:,.2f}\n    Detail: {d.get('details', 'N/A')}")
        out.append("")
    out.append("──────────────────\n" + f"🛡️ <b>ALL ADMINS TOTAL HOLD: ₹{gtot:,.2f}</b>")
    await u.message.reply_text("\n".join(out), parse_mode="HTML")

async def purge_pinned_service_msg(u: Update, c: ContextTypes.DEFAULT_TYPE):
    try:
        if u.message and u.message.pinned_message: 
            await u.message.delete()
    except: 
        pass

async def handle_edited_msg(u: Update, c: ContextTypes.DEFAULT_TYPE):
    em = u.edited_message
    if not em or not em.from_user or em.from_user.id == OWNER_ID: 
        return
    try:
        if any(a.user.id == em.from_user.id for a in await c.bot.get_chat_administrators(em.chat_id)): 
            return
    except: 
        pass
    try:
        await em.delete()
        await c.bot.send_message(chat_id=em.chat_id, text=f"⚠️ {em.from_user.mention_html()} <b>EDITED FORM/MESSAGE NOT ALLOWED ⚠️</b>", parse_mode="HTML")
    except: 
        pass

async def handle_txt(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not u.message or not u.message.text: 
        return
    t = u.message.text.strip().lower()
    if t in ["form", ".form"]: 
      

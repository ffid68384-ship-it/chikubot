import os, re, unicodedata, threading, asyncio
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

web_app = Flask(__name__)
@web_app.route('/')
def home(): return "Chiku Escrow 24/7"
def run_web(): web_app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

BOT_TOKEN = "8938665546:AAFz121wlq59_UvVIAWlapHfh58q_Uq7b1E"
OWNER_ID = 7364435907
PROOF_CHANNEL = ""
DEALS_DB, STATS = {}, {"total_deals": 0, "total_volume": 0.0, "total_fees": 0.0}
DEAL_COUNTER, LATEST_ACTIVE_DEAL, LATEST_PINNED_MSG_ID = 1, None, None

async def is_admin(u: Update, c: ContextTypes.DEFAULT_TYPE):
    uid = u.effective_user.id
    if uid == OWNER_ID: return True
    try:
        admins = await c.bot.get_chat_administrators(u.effective_chat.id)
        return any(a.user.id == uid for a in admins)
    except: return False

def norm_txt(t):
    if not t: return ""
    t = unicodedata.normalize('NFKD', str(t))
    conv = {'ꜱ':'s','s':'s','ᴇ':'e','e':'e','ʟ':'l','l':'l','ʀ':'r','r':'r','ʙ':'b','b':'b','ᴜ':'u','u':'u','ʏ':'y','y':'y','ᴅ':'d','d':'d','ᴀ':'a','a':'a','ᴛ':'t','t':'t','ɪ':'i','i':'i','ᴏ':'o','o':'o','ᴡ':'w','w':'w','м':'m','m':'m','ɴ':'n','n':'n','ᴄ':'c','c':'c','ʜ':'h','h':'h','ᴋ':'k','k':'k','ᴘ':'p','p':'p'}
    return "".join(conv.get(ch, ch) for ch in t)

def get_fee(amt):
    if amt <= 0: return 0.0, "0%", "0₹", 0.0
    if amt <= 190: return 10.0, "Flat ₹10", "Rs 10", amt - 10.0
    if amt <= 599: return 20.0, "Flat ₹20", "Rs 20", amt - 20.0
    if amt <= 2000: return round(amt*0.035, 2), "3.5%", f"3.5% - {round(amt*0.035):,.0f}₹", amt - round(amt*0.035, 2)
    return round(amt*0.03, 2), "3%", f"3% - {round(amt*0.03):,.0f}₹", amt - round(amt*0.03, 2)

def parse_amt(val):
    if not val: return 0.0
    c = str(val).lower().replace("₹","").replace(",","").replace("rs","").strip()
    m = re.search(r"(\d+(\.\d+)?)(\s*k)?", c)
    return float(m.group(1)) * (1000 if m.group(3) else 1) if m else 0.0

def extract_f(raw):
    n = norm_txt(raw)
    f = {"seller": "", "buyer": "", "details": "", "amount": "", "till": "SECURE", "deal_id": ""}
    dm = re.search(r"DL[-_ ]*CHIKU[-_ ]*\d+", n, re.I)
    if dm: f["deal_id"] = re.sub(r"\s+", "", dm.group(0).upper().replace("_", "-"))
    for k, p in [("seller", r"seller\s*[:\-]\s*([^\n\r]+)"), ("buyer", r"buyer\s*[:\-]\s*([^\n\r]+)"), ("amount", r"(?:deal\s*amount|amount|released)\s*[:\-]\s*([^\n\r]+)"), ("details", r"(?:deal\s*details|deal\s*deatails|details)\s*[:\-]\s*([^\n\r]+)"), ("till", r"(?:escrow\s*till|till)\s*[:\-]\s*([^\n\r]+)")]:
        m = re.search(p, n, re.I)
        if m: f[k] = m.group(1).strip()
    return f

async def res_uid(u, rep, ctx, cid):
    if not u or u == "N/A": return u or "N/A"
    cln = u.strip()
    if "(" in cln and ")" in cln: return cln
    if cln.isdigit(): return f'<a href="tg://user?id={cln}">{cln}</a> ({cln})'
    if rep and rep.entities:
        for ent in rep.entities:
            if ent.type == "text_mention" and ent.user:
                usr = ent.user
                mt = rep.text[ent.offset:ent.offset+ent.length] if rep.text else ""
                if (cln.lower() in mt.lower()) or (usr.first_name and cln.lower() in usr.first_name.lower()):
                    return f'{usr.mention_html()} ({usr.id})'
    if rep and rep.from_user:
        fu = rep.from_user
        if (fu.first_name and cln.lower() in fu.first_name.lower()) or (fu.username and cln.replace("@","").lower() == fu.username.lower()):
            return f'{fu.mention_html()} ({fu.id})'
    pure_u = cln.replace("@", "")
    if cln.startswith("@"):
        try:
            m = await ctx.bot.get_chat_member(cid, f"@{pure_u}")
            if m and m.user: return f"@{pure_u} ({m.user.id})"
        except: pass
        return f"@{pure_u}"
    return cln

async def safe_del(u: Update):
    try:
        if u.message: await u.message.delete()
    except: pass

async def unpin_old(c: ContextTypes.DEFAULT_TYPE, cid, mid=None):
    global LATEST_PINNED_MSG_ID
    tgt = mid or LATEST_PINNED_MSG_ID
    if tgt:
        try: await c.bot.unpin_chat_message(chat_id=cid, message_id=tgt)
        except: pass

async def send_fee_result(u: Update, amt: float):
    f, r, _, rcv = get_fee(amt)
    await u.message.reply_text(f"📊 <b>@CHIKUESCROWSERVICE FEE CALCULATOR</b>\n━━━━━━━━━━━━━━━━━━━\n💰 <b>Deal Amount:</b> ₹{amt:,.0f}\n⚡ <b>Fee Rate:</b> {r}\n💵 <b>Escrow Fee:</b> ₹{f:,.0f}\n━━━━━━━━━━━━━━━━━━━\n✅ <b>Seller Receives:</b> ₹{rcv:,.0f}\n\n📱 <b>RG :</b> @CHIKUNXT", parse_mode="HTML")

async def form(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text("<b>ESCROW DEAL FORM</b>\n\n• <b>SELLER :</b> \n• <b>BUYER :</b> \n• <b>DEAL DETAILS :</b> \n• <b>DEAL AMOUNT :</b> \n• <b>ESCROW TILL :</b> SECURE\n• <b>FOR RELEASE SELLER UPI :</b> \n\n<i>FOR MORE PROOFS CHECK GROUP PIN MESSAGES..</i>\n\n⚠️ <b>ESCROW FEES IS NON-REFUNDABLE NO MATTER IF THE DEAL GETS CANCELLED</b> ⚠️", parse_mode="HTML")

async def fee_command(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not c.args:
        await u.message.reply_text("<b>@CHIKUESCROWSERVICE CHARGES -</b>\n\n• Under ₹190 - ₹10\n• ₹191 To ₹599 - ₹20\n• ₹600 To ₹2000 - 3.5%\n• ₹2001 To ₹3000 - 3%\n• Upper Than ₹3000 - 3%\n\n📱 <b>RG :</b> @CHIKUNXT\n━━━━━━━━━━━━━━━━━━━\n💡 Check amount: <code>fees 2000</code>", parse_mode="HTML")
        return
    amt = parse_amt(c.args[0])
    if amt > 0: await send_fee_result(u, amt)

async def start_deal(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global DEAL_COUNTER, LATEST_ACTIVE_DEAL, LATEST_PINNED_MSG_ID
    if not await is_admin(u, c): return
    rep = u.message.reply_to_message
    if not rep or not (rep.text or rep.caption):
        await u.message.reply_text("⚠️ Bhare hue <b>FORM</b> ka <b>Reply</b> karke <code>/deal</code> likhein!", parse_mode="HTML")
        return
    try: await c.bot.unpin_chat_message(chat_id=u.effective_chat.id, message_id=rep.message_id)
    except: pass
    f = extract_f(rep.text or rep.caption)
    s_fmt = await res_uid(f["seller"] or "N/A", rep, c, u.effective_chat.id)
    b_fmt = await res_uid(f["buyer"] or "N/A", rep, c, u.effective_chat.id)
    amt_num = parse_amt(f["amount"])
    fee_num, fee_line = (get_fee(amt_num)[0], f"\n\nFees {get_fee(amt_num)[2]}") if amt_num > 0 else (0.0, "")
    did = f"DL-CHIKU-{DEAL_COUNTER:02d}"
    DEAL_COUNTER += 1
    LATEST_ACTIVE_DEAL = did
    eu = u.effective_user
    etag = f"@{eu.username}" if eu.username else eu.first_name
    amt_display = f"₹{amt_num:,.0f}" if amt_num > 0 else (f['amount'] or 'N/A')
    slip = f"<b>ESCROW DEAL</b>\n🪪 <b>DEAL ID:</b> {did}\n\n• <b>ꜱᴇʟʟᴇʀ :</b> {s_fmt}\n• <b>ʙᴜʏᴇʀ  :</b> {b_fmt}\n\n• <b>ᴅᴇᴀʟ ᴅᴇᴀᴛᴀɪʟꜱ :</b> {f['details'] or 'N/A'}\n• <b>ᴅᴇᴀʟ ᴀᴍᴏᴜɴᴛ :</b> {amt_display}\n• <b>ᴇꜱᴄʀᴏᴡ ᴛɪʟʟ :</b> {f['till']}\n\n<b>Escrower :</b> {eu.mention_html()} ({eu.id}){fee_line}"
    sm = await c.bot.send_message(chat_id=u.effective_chat.id, text=slip, parse_mode="HTML")
    try:
        await c.bot.pin_chat_message(chat_id=u.effective_chat.id, message_id=sm.message_id, disable_notification=True)
        LATEST_PINNED_MSG_ID = sm.message_id
    except: pass
    DEALS_DB[did] = {"status": "ACTIVE", "seller": s_fmt, "buyer": b_fmt, "amount": amt_num, "fee": fee_num, "escrower": etag, "details": f["details"] or "N/A", "msg_id": sm.message_id}

async def close_deal(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global DEAL_COUNTER, LATEST_ACTIVE_DEAL, LATEST_PINNED_MSG_ID
    await safe_del(u)
    if not await is_admin(u, c): return
    cid, rep, did, amt_str, buyer, seller, rep_mid = u.effective_chat.id, u.message.reply_to_message, None, "", "", "", None
    if rep and (rep.text or rep.caption):
        rep_mid, f = rep.message_id, extract_f(rep.text or rep.caption)
        did = f["deal_id"]
        if did and did in DEALS_DB:
            d = DEALS_DB[did]
            amt_str, seller, buyer, rep_mid = str(d["amount"]), d["seller"], d["buyer"], d.get("msg_id", rep_mid)
        else: amt_str, seller, buyer = f["amount"], f["seller"], f["buyer"]
    if not did and LATEST_ACTIVE_DEAL and LATEST_ACTIVE_DEAL in DEALS_DB:
        did = LATEST_ACTIVE_DEAL
        d = DEALS_DB[did]
        amt_str, seller, buyer, rep_mid = str(d["amount"]), d["seller"], d["buyer"], d.get("msg_id")
    if len(c.args) >= 1 and not amt_str: amt_str = c.args[0]
    if len(c.args) >= 2 and not buyer: buyer = c.args[1]
    if len(c.args) >= 3 and not seller: seller = c.args[2]
    amt_num = parse_amt(amt_str)
    seller_tag = seller.split()[0] if seller else "@Seller"
    buyer_tag = buyer.split()[0] if buyer else "@Buyer"
    eu = u.effective_user
    etag = f"@{eu.username}" if eu.username else eu.mention_html()
    if not did:
        did = f"DL-CHIKU-{DEAL_COUNTER:02d}"
        DEAL_COUNTER += 1
    STATS["total_deals"] += 1
    STATS["total_volume"] += amt_num
    STATS["total_fees"] += get_fee(amt_num)[0]
    DEALS_DB[did] = {"status": "COMPLETED", "seller": seller, "buyer": buyer, "amount": amt_num, "fee": get_fee(amt_num)[0], "escrower": etag, "details": "Completed Deal"}
    LATEST_ACTIVE_DEAL = did
    await unpin_old(c, cid, rep_mid)
    amt_disp = f"₹{amt_num:,.2f}" if amt_num > 0 else "Deal Amount"
    txt = f"✅ <b>Deal Completed</b>\n🪪 <b>Trade ID:</b>\n{did}\n📤 <b>Released:</b> {amt_disp}\n👤 <b>Escrowed By:</b>\n{etag}\n\n~ {buyer_tag} and {seller_tag}\nare requested to drop the\nvouch before leaving 👇🏻\n\n<code>Vouch @chikuescrowservice for {amt_disp} smooth escrow deal</code>"
    sm = await c.bot.send_message(chat_id=cid, text=txt, parse_mode="HTML")
    try:
        await c.bot.pin_chat_message(chat_id=cid, message_id=sm.message_id, disable_notification=True)
        LATEST_PINNED_MSG_ID = sm.message_id
    except: pass
    if PROOF_CHANNEL:
        try: await c.bot.send_message(chat_id=PROOF_CHANNEL, text=txt, parse_mode="HTML")
        except: pass

async def hold_deal(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global LATEST_ACTIVE_DEAL, LATEST_PINNED_MSG_ID
    await safe_del(u)
    if not await is_admin(u, c): return
    cid, rep = u.effective_chat.id, u.message.reply_to_message
    rep_mid = rep.message_id if rep else None
    f = extract_f(rep.text or rep.caption) if rep and (rep.text or rep.caption) else {}
    did = f.get("deal_id") or LATEST_ACTIVE_DEAL or "UNKNOWN"
    if did in DEALS_DB: 
        DEALS_DB[did]["status"] = "ON HOLD"
        rep_mid = DEALS_DB[did].get("msg_id", rep_mid)
    await unpin_old(c, cid, rep_mid)
    rsn = " ".join(c.args) if c.args else "Verification / Dispute Under Review"
    txt = f"⏳ <b>DEAL ON HOLD</b>\n━━━━━━━━━━━━━━━━━━━\n🪪 <b>Deal ID:</b> {did}\n⚠️ <b>Reason:</b> {rsn}\n👤 <b>Action By:</b> {u.effective_user.mention_html()}\n\n🔒 <i>Payment release is paused until further update.</i>"
    sm = await c.bot.send_message(chat_id=cid, text=txt, parse_mode="HTML")
    try:
        await c.bot.pin_chat_message(chat_id=cid, message_id=sm.message_id, disable_notification=True)
        LATEST_PINNED_MSG_ID = sm.message_id
    except: pass

async def cancel_deal(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global LATEST_ACTIVE_DEAL, LATEST_PINNED_MSG_ID
    await safe_del(u)
    if not await is_admin(u, c): return
    cid, rep = u.effective_chat.id, u.message.reply_to_message
    rep_mid = rep.message_id if rep else None
    f = extract_f(rep.text or rep.caption) if rep and (rep.text or rep.caption) else {}
    did = f.get("deal_id") or LATEST_ACTIVE_DEAL or "UNKNOWN"
    rsn = " ".join(c.args) if c.args else "Mutual Agreement"
    seller, buyer, amt_str = f.get("seller", ""), f.get("buyer", ""), f.get("amount", "")
    if did in DEALS_DB:
        DEALS_DB[did]["status"] = "CANCELLED"
        seller, buyer, amt_str, rep_mid = DEALS_DB[did]["seller"], DEALS_DB[did]["buyer"], str(DEALS_DB[did]["amount"]), DEALS_DB[did].get("msg_id", rep_mid)
    await unpin_old(c, cid, rep_mid)
    s_tag, b_tag = (seller.split()[0] if seller else "@Seller"), (buyer.split()[0] if buyer else "@Buyer")
    amt_num = parse_amt(amt_str)
    amt_display = f"₹{amt_num:,.0f}" if amt_num > 0 else "N/A"
    txt = f"❌ <b>DEAL CANCELLED</b>\n━━━━━━━━━━━━━━━━━━━\n🪪 <b>Deal ID:</b> {did}\n💰 <b>Amount:</b> {amt_display}\n👤 <b>Seller:</b> {s_tag}\n👤 <b>Buyer:</b> {b_tag}\n⚠️ <b>Reason:</b> {rsn}\n👤 <b>Action By:</b> {u.effective_user.mention_html()}"
    sm = await c.bot.send_message(chat_id=cid, text=txt, parse_mode="HTML")
    try:
        await c.bot.pin_chat_message(chat_id=cid, message_id=sm.message_id, disable_notification=True)
        LATEST_PINNED_MSG_ID = sm.message_id
    except: pass
    if LATEST_ACTIVE_DEAL == did: LATEST_ACTIVE_DEAL = None

async def refund_deal(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global LATEST_ACTIVE_DEAL, LATEST_PINNED_MSG_ID
    await safe_del(u)
    if not await is_admin(u, c): return
    cid, rep = u.effective_chat.id, u.message.reply_to_message
    rep_mid = rep.message_id if rep else None
    f = extract_f(rep.text or rep.caption) if rep and (rep.text or rep.caption) else {}
    did = f.get("deal_id") or LATEST_ACTIVE_DEAL or "N/A"
    buyer, amt_str = f.get("buyer", ""), f.get("amount", "")
    if did in DEALS_DB:
        DEALS_DB[did]["status"] = "REFUNDED"
        buyer, amt_str, rep_mid = DEALS_DB[did]["buyer"], str(DEALS_DB[did]["amount"]), DEALS_DB[did].get("msg_id", rep_mid)
    await unpin_old(c, cid, rep_mid)
    b_tag = buyer.split()[0] if buyer else "@Buyer"
    amt_num = parse_amt(amt_str)
    amt_disp = f"₹{amt_num:,.0f}" if amt_num > 0 else "Deal Amount"
    txt = f"↩️ <b>ESCROW REFUND PROCESSED</b>\n━━━━━━━━━━━━━━━━━━━\n🪪 <b>Deal ID:</b> {did}\n👤 <b>Refund To:</b> {b_tag}\n💰 <b>Amount:</b> {amt_disp}\n👤 <b>Escrower:</b> {u.effective_user.mention_html()}\n\n⚠️ <i>Escrow fees non-refundable as per policy.</i>"
    sm = await c.bot.send_message(chat_id=cid, text=txt, parse_mode="HTML")
    try:
        await c.bot.pin_chat_message(chat_id=cid, message_id=sm.message_id, disable_notification=True)
        LATEST_PINNED_MSG_ID = sm.message_id
    except: pass
    if LATEST_ACTIVE_DEAL == did: LATEST_ACTIVE_DEAL = None

async def status_deal(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global LATEST_ACTIVE_DEAL
    did = None
    rep = u.message.reply_to_message
    raw_rep = rep.text or rep.caption if rep else ""
    if raw_rep: did = extract_f(raw_rep).get("deal_id")
    if not did and c.args:
        raw_arg = " ".join(c.args)
        did = extract_f(raw_arg).get("deal_id") or re.sub(r"\s+", "", raw_arg.upper().replace("_", "-"))
    if not did and LATEST_ACTIVE_DEAL: did = LATEST_ACTIVE_DEAL
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
        st = "COMPLETED" if "completed" in raw_rep.lower() else ("ON HOLD" if "hold" in raw_rep.lower() else ("CANCELLED" if "cancelled" in raw_rep.lower() else "ACTIVE"))
        bdg = {"ACTIVE": "🟢", "COMPLETED": "✅", "CANCELLED": "❌", "ON HOLD": "⏳"}.get(st, "📌")
        amt_val = parse_amt(f["amount"])
        amt_disp = f"₹{amt_val:,.0f}" if amt_val > 0 else (f["amount"] or "Deal Amount")
        await u.message.reply_text(f"🔍 <b>DEAL STATUS</b>\n🪪 <b>ID:</b> {did}\n📌 <b>Status:</b> {bdg} {st}\n💰 <b>Amount:</b> {amt_disp}\n👤 <b>Seller:</b> {f['seller'] or 'N/A'}\n👤 <b>Buyer:</b> {f['buyer'] or 'N/A'}", parse_mode="HTML")
        return
    await u.message.reply_text(f"❓ Deal ID <code>{did}</code> record me nahi mili.", parse_mode="HTML")

async def stats_cmd(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(f"📈 <b>@CHIKUESCROWSERVICE STATS</b>\n━━━━━━━━━━━━━━━━━━━\n🤝 <b>Total Deals:</b> {STATS['total_deals']}\n💼 <b>Total Volume:</b> ₹{STATS['total_volume']:,.2f}\n💵 <b>Total Fees:</b> ₹{STATS['total_fees']:,.2f}", parse_mode="HTML")

async def admin_hold_cmd(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if u.effective_user.id != OWNER_ID: return
    hd = {k: v for k, v in DEALS_DB.items() if v["status"] in ["ACTIVE", "ON HOLD"]}
    if not hd:
        await u.message.reply_text("🛡️ <b>ADMIN HOLD</b>\n\nAbhi koi active hold deal nahi hai.", parse_mode="HTML")
        return
    ag, gtot = {}, 0.0
    for did, info in hd.items():
        adm = info.get("escrower", "Unknown Escrower")
        ag.setdefault(adm, []).append((did, info))
        gtot += info["amount"]
    out = ["🛡️ <b>ADMIN HOLD</b>\n"]
    for adm, deals in ag.items():
        tot = sum(d[1]["amount"] for d in deals)
        out.append(f"🛡️ <b>{adm}</b> — Total Hold: ₹{tot:,.2f}")
        for did, d in deals:
            _, rate, _, net = get_fee(d["amount"])
            b = d["buyer"].split()[0] if d["buyer"] else "@Buyer"
            s = d["seller"].split()[0] if d["seller"] else "@Seller"
            out.append(f"  • <b>{did}</b> — ₹{d['amount']:,.2f}\n    Buyer: {b} | Seller: {s}\n    Fee: {rate} — Net: ₹{net:,.2f}\n    Detail: {d.get('details', 'N/A')}")
        out.append("")
    out.append("──────────────────")
    out.append(f"🛡️ <b>ALL ADMINS TOTAL HOLD: ₹{gtot:,.2f}</b>")
    await u.message.reply_text("\n".join(out), parse_mode="HTML")

async def purge_pinned_service_msg(u: Update, c: ContextTypes.DEFAULT_TYPE):
    try:
        if u.message and u.message.pinned_message: await u.message.delete()
    except: pass

async def handle_edited_msg(u: Update, c: ContextTypes.DEFAULT_TYPE):
    em = u.edited_message
    if not em or not em.from_user: return
    uid = em.from_user.id
    if uid == OWNER_ID: return
    try:
        admins = await c.bot.get_chat_administrators(em.chat_id)
        if any(a.user.id == uid for a in admins): return
    except: pass
    tag = em.from_user.mention_html()
    try:
        await em.delete()
        await c.bot.send_message(chat_id=em.chat_id, text=f"⚠️ {tag} <b>EDITED FORM/MESSAGE NOT ALLOWED ⚠️</b>", parse_mode="HTML")
    except: pass

async def handle_txt(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not u.message or not u.message.text: return
    t = u.message.text.strip().lower()
    if t in ["form", ".form"]: await form(u, c)
    elif t in ["fees", "fee", ".fee", ".fees"]: await fee_command(u, c)
    elif t in ["adminhold", ".adminhold"]: await admin_hold_cmd(u, c)
    fm = re.match(r"^(?:fee|fees|\.fee|\.fees|\/fee|\/fees)\s+([^\s]+)", t)
    if fm:
        amt = parse_amt(fm.group(1))
        if amt > 0: await send_fee_result(u, amt)

if __name__ == '__main__':
    threading.Thread(target=run_web, daemon=True).start()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    cmds = [("form", form), ("fee", fee_command), ("fees", fee_command), ("deal", start_deal), ("close", close_deal), ("hold", hold_deal), ("cancel", cancel_deal), ("refund", refund_deal), ("status", status_deal), ("stats", stats_cmd), ("adminhold", admin_hold_cmd)]
    for cmd, fn in cmds: app.add_handler(CommandHandler(cmd, fn))
    app.add_handler(MessageHandler(filters.StatusUpdate.PINNED_MESSAGE, purge_pinned_service_msg))
    app.add_handler(MessageHandler(filters.UpdateType.EDITED_MESSAGE, handle_edited_msg))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_txt))
    app.run_polling(drop_pending_updates=True)
    

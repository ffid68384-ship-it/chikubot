import os, re, unicodedata, threading, asyncio
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

web_app = Flask(__name__)
@web_app.route('/')
def home(): return "Chiku Escrow Running 24/7"

def run_web():
    web_app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

BOT_TOKEN = "8938665546:AAFz121wlq59_UvVIAWlapHfh58q_Uq7b1E"
OWNER_ID = 7364435907
PROOF_CHANNEL = ""

DEALS_DB = {}
STATS = {"total_deals": 0, "total_volume": 0.0, "total_fees": 0.0}
DEAL_COUNTER = 1
LATEST_ACTIVE_DEAL = None

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid == OWNER_ID: return True
    try:
        admins = await context.bot.get_chat_administrators(update.effective_chat.id)
        return any(a.user.id == uid for a in admins)
    except: return False

def norm_txt(t):
    if not t: return ""
    t = unicodedata.normalize('NFKD', str(t))
    conv = {
        'ꜱ':'s','s':'s','ᴇ':'e','e':'e','ʟ':'l','l':'l','ʀ':'r','r':'r',
        'ʙ':'b','b':'b','ᴜ':'u','u':'u','ʏ':'y','y':'y','ᴅ':'d','d':'d',
        'ᴀ':'a','a':'a','ᴛ':'t','t':'t','ɪ':'i','i':'i','ᴏ':'o','o':'o',
        'ᴡ':'w','w':'w','м':'m','m':'m','ɴ':'n','n':'n','ᴄ':'c','c':'c',
        'ʜ':'h','h':'h','ᴋ':'k','k':'k','ᴘ':'p','p':'p'
    }
    res = []
    for ch in t:
        res.append(conv.get(ch, ch))
    return "".join(res)

def get_fee(amt):
    if amt <= 0: return 0.0, "0%", "0₹", 0.0
    if amt <= 190: f, r, d = 10.0, "Flat ₹10", "Rs 10"
    elif amt <= 599: f, r, d = 20.0, "Flat ₹20", "Rs 20"
    elif amt <= 2000: f, r, d = round(amt*0.035, 2), "3.5%", f"3.5% - {round(amt*0.035):,.0f}₹"
    else: f, r, d = round(amt*0.03, 2), "3%", f"3% - {round(amt*0.03):,.0f}₹"
    return f, r, d, amt - f

def parse_amt(val):
    if not val: return 0.0
    c = str(val).lower().replace("₹","").replace(",","").replace("rs","").strip()
    m = re.search(r"(\d+(\.\d+)?)(\s*k)?", c)
    if not m: return 0.0
    n = float(m.group(1))
    return n * 1000 if m.group(3) else n

def extract_f(raw_text):
    n = norm_txt(raw_text)
    f = {"seller": "", "buyer": "", "details": "", "amount": "", "till": "SECURE", "deal_id": ""}
    
    dm = re.search(r"DL[-_]CHIKU[-_]\d+", n, re.I)
    if dm:
        f["deal_id"] = dm.group(0).upper().replace("_", "-")

    sm = re.search(r"seller\s*[:\-]\s*([^\n\r]+)", n, re.I)
    if sm: f["seller"] = sm.group(1).strip()

    bm = re.search(r"buyer\s*[:\-]\s*([^\n\r]+)", n, re.I)
    if bm: f["buyer"] = bm.group(1).strip()

    am = re.search(r"(?:deal\s*amount|amount)\s*[:\-]\s*([^\n\r]+)", n, re.I)
    if am: f["amount"] = am.group(1).strip()

    dtm = re.search(r"(?:deal\s*details|deal\s*deatails|details)\s*[:\-]\s*([^\n\r]+)", n, re.I)
    if dtm: f["details"] = dtm.group(1).strip()

    tm = re.search(r"(?:escrow\s*till|till)\s*[:\-]\s*([^\n\r]+)", n, re.I)
    if tm: f["till"] = tm.group(1).strip()

    return f

async def res_uid(u, rep, ctx, cid):
    if not u or u == "N/A" or ("(" in u and ")" in u): return u or "N/A"
    cln = u.strip().replace("@","")
    if rep and rep.entities:
        for e in rep.entities:
            if e.type == "text_mention" and e.user:
                if e.user.username and e.user.username.lower() == cln.lower():
                    return f"@{e.user.username} ({e.user.id})"
                elif e.user.first_name and cln.lower() in e.user.first_name.lower():
                    return f"{e.user.mention_html()} ({e.user.id})"
            elif e.type == "mention":
                mt = rep.text[e.offset:e.offset+e.length].lstrip("@")
                if mt.lower() == cln.lower():
                    try:
                        m = await ctx.bot.get_chat_member(cid, f"@{mt}")
                        if m and m.user: return f"@{mt} ({m.user.id})"
                    except: pass
    try:
        m = await ctx.bot.get_chat_member(cid, f"@{cln}")
        if m and m.user: return f"@{cln} ({m.user.id})"
    except: pass
    return f"@{cln}" if not u.startswith("@") else u

async def safe_delete_cmd(update: Update):
    try:
        if update.message:
            await update.message.delete()
    except Exception:
        pass

async def send_fee_result(update: Update, amt: float):
    fee, rate, dsp, rcv = get_fee(amt)
    await update.message.reply_text(
        f"📊 <b>@CHIKUESCROWSERVICE FEE CALCULATOR</b>\n━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Deal Amount:</b> ₹{amt:,.0f}\n⚡ <b>Fee Rate:</b> {rate}\n💵 <b>Escrow Fee:</b> ₹{fee:,.0f}\n"
        f"━━━━━━━━━━━━━━━━━━━\n✅ <b>Seller Receives:</b> ₹{rcv:,.0f}\n\n📱 <b>RG :</b> @CHIKUNXT",
        parse_mode="HTML"
    )

async def form(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(
        "<b>ESCROW DEAL FORM</b>\n\n• <b>SELLER :</b> \n• <b>BUYER :</b> \n"
        "• <b>DEAL DETAILS :</b> \n• <b>DEAL AMOUNT :</b> \n• <b>ESCROW TILL :</b> SECURE\n"
        "• <b>FOR RELEASE SELLER UPI :</b> \n\n"
        "<i>FOR MORE PROOFS CHECK GROUP PIN MESSAGES..</i>\n\n"
        "⚠️ <b>ESCROW FEES IS NON-REFUNDABLE NO MATTER IF THE DEAL GETS CANCELLED</b> ⚠️",
        parse_mode="HTML"
    )

async def fee_command(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not c.args:
        await u.message.reply_text(
            "<b>@CHIKUESCROWSERVICE CHARGES -</b>\n\n• Under ₹190 - ₹10\n• ₹191 To ₹599 - ₹20\n"
            "• ₹600 To ₹2000 - 3.5%\n• ₹2001 To ₹3000 - 3%\n• Upper Than ₹3000 - 3%\n\n"
            "📱 <b>RG :</b> @CHIKUNXT\n━━━━━━━━━━━━━━━━━━━\n💡 Check amount: <code>fees 2000</code> ya <code>/fee 2000</code>",
            parse_mode="HTML"
        )
        return
    amt = parse_amt(c.args[0])
    if amt <= 0:
        await u.message.reply_text("❌ Sahi amount likhein (e.g. <code>fees 2000</code>)!", parse_mode="HTML")
        return
    await send_fee_result(u, amt)

async def start_deal(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global DEAL_COUNTER, LATEST_ACTIVE_DEAL
    if not await is_admin(u, c):
        await u.message.reply_text("❌ Sirf escrow admin yeh command chala sakta hai.")
        return
    rep = u.message.reply_to_message
    if not rep or not (rep.text or rep.caption):
        await u.message.reply_text("⚠️ Bhare hue <b>FORM</b> ka <b>Reply</b> karke <code>/deal</code> likhein!", parse_mode="HTML")
        return
    f = extract_f(rep.text or rep.caption)
    s_fmt = await res_uid(f["seller"] or "N/A", rep, c, u.effective_chat.id)
    b_fmt = await res_uid(f["buyer"] or "N/A", rep, c, u.effective_chat.id)
    amt_num = parse_amt(f["amount"])
    fee_num, fee_line = 0.0, ""
    if amt_num > 0:
        fee_num, _, dsp, _ = get_fee(amt_num)
        fee_line = f"\n\nFees {dsp}"
    
    did = f"DL-CHIKU-{DEAL_COUNTER:02d}"
    DEAL_COUNTER += 1
    LATEST_ACTIVE_DEAL = did

    eu = u.effective_user
    etag = f"@{eu.username}" if eu.username else eu.first_name
    amt_display = f"₹{amt_num:,.0f}" if amt_num > 0 else (f['amount'] or 'N/A')

    DEALS_DB[did] = {
        "status": "ACTIVE",
        "seller": s_fmt,
        "buyer": b_fmt,
        "amount": amt_num,
        "fee": fee_num,
        "escrower": etag,
        "details": f["details"] or "N/A"
    }

    slip = (
        f"<b>ESCROW DEAL</b>\n🪪 <b>DEAL ID:</b> {did}\n\n• <b>ꜱᴇʟʟᴇʀ :</b> {s_fmt}\n• <b>ʙᴜʏᴇʀ  :</b> {b_fmt}\n\n"
        f"• <b>ᴅᴇᴀʟ ᴅᴇᴀᴛᴀɪʟꜱ :</b> {f['details'] or 'N/A'}\n• <b>ᴅᴇᴀʟ ᴀᴍᴏᴜɴᴛ :</b> {amt_display}\n"
        f"• <b>ᴇꜱᴄʀᴏᴡ ᴛɪʟʟ :</b> {f['till']}\n\n<b>Escrower :</b> {eu.mention_html()} ({eu.id}){fee_line}"
    )
    sm = await c.bot.send_message(chat_id=u.effective_chat.id, text=slip, parse_mode="HTML")
    try:
        await c.bot.pin_chat_message(chat_id=u.effective_chat.id, message_id=sm.message_id, disable_notification=True)
    except: pass

async def close_deal(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global DEAL_COUNTER, LATEST_ACTIVE_DEAL
    # 1. Sabse pehle command delete karein
    await safe_delete_cmd(u)

    if not await is_admin(u, c):
        return
    
    chat_id = u.effective_chat.id
    amt_str, buyer, seller, did = "", "", "", None
    rep = u.message.reply_to_message
    
    if rep and (rep.text or rep.caption):
        raw = rep.text or rep.caption
        f = extract_f(raw)
        did = f["deal_id"]
        if did and did in DEALS_DB:
            d = DEALS_DB[did]
            amt_str = str(d["amount"])
            seller = d["seller"]
            buyer = d["buyer"]
        else:
            if f["amount"]: amt_str = f["amount"]
            if f["seller"]: seller = f["seller"]
            if f["buyer"]: buyer = f["buyer"]
    
    if not did and LATEST_ACTIVE_DEAL and LATEST_ACTIVE_DEAL in DEALS_DB:
        did = LATEST_ACTIVE_DEAL
        d = DEALS_DB[did]
        amt_str = str(d["amount"])
        seller = d["seller"]
        buyer = d["buyer"]

    if len(c.args) >= 1 and not amt_str: amt_str = c.args[0]
    if len(c.args) >= 2 and not buyer: buyer = c.args[1]
    if len(c.args) >= 3 and not seller: seller = c.args[2]

    amt_num = parse_amt(amt_str)
    
    if seller:
        sm = re.search(r"@([A-Za-z0-9_]+)", seller)
        seller = f"@{sm.group(1)}" if sm else seller.split()[0]
    else:
        seller = "@Seller"

    if buyer:
        bm = re.search(r"@([A-Za-z0-9_]+)", buyer)
        buyer = f"@{bm.group(1)}" if bm else buyer.split()[0]
    else:
        buyer = "@Buyer"

    eu = u.effective_user
    etag = f"@{eu.username}" if eu.username else eu.mention_html()
    
    if not did:
        did = f"DL-CHIKU-{DEAL_COUNTER:02d}"
        DEAL_COUNTER += 1

    fee_num, _, _, _ = get_fee(amt_num)
    STATS["total_deals"] += 1
    STATS["total_volume"] += amt_num
    STATS["total_fees"] += fee_num
    if did in DEALS_DB: 
        DEALS_DB[did]["status"] = "COMPLETED"
    if LATEST_ACTIVE_DEAL == did:
        LATEST_ACTIVE_DEAL = None

    amt_disp = f"₹{amt_num:,.2f}" if amt_num > 0 else "Deal Amount"

    txt = (
        f"✅ <b>Deal Completed</b>\n🪪 <b>Trade ID:</b>\n{did}\n📤 <b>Released:</b> {amt_disp}\n"
        f"👤 <b>Escrowed By:</b>\n{etag}\n\n~ {buyer} and {seller}\nare requested to drop the\n"
        f"vouch before leaving 👇🏻\n\n<code>Vouch @chikuescrowservice for {amt_disp} smooth escrow deal</code>"
    )
    sm = await c.bot.send_message(chat_id=chat_id, text=txt, parse_mode="HTML")
    try:
        await c.bot.pin_chat_message(chat_id=chat_id, message_id=sm.message_id, disable_notification=True)
    except: pass

    if PROOF_CHANNEL:
        try: await c.bot.send_message(chat_id=PROOF_CHANNEL, text=txt, parse_mode="HTML")
        except: pass

async def hold_deal(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global LATEST_ACTIVE_DEAL
    await safe_delete_cmd(u)
    if not await is_admin(u, c): return

    chat_id = u.effective_chat.id
    rep = u.message.reply_to_message
    f = extract_f(rep.text or rep.caption) if rep and (rep.text or rep.caption) else {}
    did = f.get("deal_id") or LATEST_ACTIVE_DEAL or "UNKNOWN"

    rsn = " ".join(c.args) if c.args else "Verification / Dispute Under Review"
    if did in DEALS_DB: DEALS_DB[did]["status"] = "ON HOLD"
    
    txt = (
        f"⏳ <b>DEAL ON HOLD</b>\n━━━━━━━━━━━━━━━━━━━\n"
        f"🪪 <b>Deal ID:</b> {did}\n"
        f"⚠️ <b>Reason:</b> {rsn}\n"
        f"👤 <b>Action By:</b> {u.effective_user.mention_html()}\n\n"
        f"🔒 <i>Payment release is paused until further update.</i>"
    )
    sm = await c.bot.send_message(chat_id=chat_id, text=txt, parse_mode="HTML")
    try:
        await c.bot.pin_chat_message(chat_id=chat_id, message_id=sm.message_id, disable_notification=True)
    except: pass

async def cancel_deal(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global LATEST_ACTIVE_DEAL
    await safe_delete_cmd(u)
    if not await is_admin(u, c): return

    chat_id = u.effective_chat.id
    rep = u.message.reply_to_message
    f = extract_f(rep.text or rep.caption) if rep and (rep.text or rep.caption) else {}
    did = f.get("deal_id") or LATEST_ACTIVE_DEAL or "UNKNOWN"

    rsn = " ".join(c.args) if c.args else "Mutual Agreement"
    seller, buyer, amt_str = f.get("seller", ""), f.get("buyer", ""), f.get("amount", "")
    
    if did in DEALS_DB:
        DEALS_DB[did]["status"] = "CANCELLED"
        seller = DEALS_DB[did]["seller"]
        buyer = DEALS_DB[did]["buyer"]
        amt_str = str(DEALS_DB[did]["amount"])

    s_tag = seller.split()[0] if seller else "@Seller"
    b_tag = buyer.split()[0] if buyer else "@Buyer"
    amt_num = parse_amt(amt_str)
    amt_display = f"₹{amt_num:,.0f}" if amt_num > 0 else "N/A"

    txt = (
        f"❌ <b>DEAL CANCELLED</b>\n━━━━━━━━━━━━━━━━━━━\n"
        f"🪪 <b>Deal ID:</b> {did}\n"
        f"💰 <b>Amount:</b> {amt_display}\n"
        f"👤 <b>Seller:</b> {s_tag}\n"
        f"👤 <b>Buyer:</b> {b_tag}\n"
        f"⚠️ <b>Reason:</b> {rsn}\n"
        f"👤 <b>Action By:</b> {u.effective_user.mention_html()}"
    )
    sm = await c.bot.send_message(chat_id=chat_id, text=txt, parse_mode="HTML")
    try:
        await c.bot.pin_chat_message(chat_id=chat_id, message_id=sm.message_id, disable_notification=True)
    except: pass
    
    if LATEST_ACTIVE_DEAL == did: LATEST_ACTIVE_DEAL = None

async def refund_deal(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global LATEST_ACTIVE_DEAL
    await safe_delete_cmd(u)
    if not await is_admin(u, c): return

    chat_id = u.effective_chat.id
    rep = u.message.reply_to_message
    f = extract_f(rep.text or rep.caption) if rep and (rep.text or rep.caption) else {}
    did = f.get("deal_id") or LATEST_ACTIVE_DEAL or "N/A"

    buyer = f.get("buyer", "")
    amt_str = f.get("amount", "")

    if did in DEALS_DB:
        DEALS_DB[did]["status"] = "REFUNDED"
        buyer = DEALS_DB[did]["buyer"]
        amt_str = str(DEALS_DB[did]["amount"])

    b_tag = buyer.split()[0] if buyer else "@Buyer"
    amt_num = parse_amt(amt_str)
    amt_disp = f"₹{amt_num:,.0f}" if amt_num > 0 else "Deal Amount"

    txt = (
        f"↩️ <b>ESCROW REFUND PROCESSED</b>\n━━━━━━━━━━━━━━━━━━━\n"
        f"🪪 <b>Deal ID:</b> {did}\n"
        f"👤 <b>Refund To:</b> {b_tag}\n"
        f"💰 <b>Amount:</b> {amt_disp}\n"
        f"👤 <b>Escrower:</b> {u.effective_user.mention_html()}\n\n"
        f"⚠️ <i>Escrow fees non-refundable as per policy.</i>"
    )
    sm = await c.bot.send_message(chat_id=chat_id, text=txt, parse_mode="HTML")
    try:
        await c.bot.pin_chat_message(chat_id=chat_id, message_id=sm.message_id, disable_notification=True)
    except: pass
    
    if LATEST_ACTIVE_DEAL == did: LATEST_ACTIVE_DEAL = None

async def status_deal(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not c.args:
        await u.message.reply_text("⚠️ Deal ID likhein! e.g. <code>/status DL-CHIKU-01</code>", parse_mode="HTML")
        return
    did = c.args[0].upper().strip()
    if did not in DEALS_DB:
        await u.message.reply_text(f"❓ Deal ID <code>{did}</code> record me nahi mili.", parse_mode="HTML")
        return
    d = DEALS_DB[did]
    status_emoji = {"ACTIVE": "🟢", "COMPLETED": "✅", "CANCELLED": "❌", "ON HOLD": "⏳", "REFUNDED": "↩️"}
    bdg = status_emoji.get(d["status"], "📌")
    await u.message.reply_text(
        f"🔍 <b>DEAL STATUS</b>\n🪪 <b>ID:</b> {did}\n📌 <b>Status:</b> {bdg} {d['status']}\n"
        f"💰 <b>Amount:</b> ₹{d['amount']:,.0f}\n👤 <b>Seller:</b> {d['seller']}\n👤 <b>Buyer:</b> {d['buyer']}", 
        parse_mode="HTML"
    )

async def stats_cmd(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(
        f"📈 <b>@CHIKUESCROWSERVICE STATS</b>\n━━━━━━━━━━━━━━━━━━━\n"
        f"🤝 <b>Total Deals:</b> {STATS['total_deals']}\n💼 <b>Total Volume:</b> ₹{STATS['total_volume']:,.2f}\n"
        f"💵 <b>Total Fees:</b> ₹{STATS['total_fees']:,.2f}",
        parse_mode="HTML"
    )

async def admin_hold_cmd(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if u.effective_user.id != OWNER_ID:
        await u.message.reply_text("❌ Yeh command sirf Bot Owner (@CHIKUNXT) hi dekh sakta hai.")
        return

    hold_deals = {did: info for did, info in DEALS_DB.items() if info["status"] in ["ACTIVE", "ON HOLD"]}
    if not hold_deals:
        await u.message.reply_text("🛡️ <b>ADMIN HOLD</b>\n\nAbhi koi active hold deal nahi hai.", parse_mode="HTML")
        return

    admin_groups = {}
    grand_total = 0.0

    for did, info in hold_deals.items():
        admin = info.get("escrower", "Unknown Escrower")
        if admin not in admin_groups: admin_groups[admin] = []
        admin_groups[admin].append((did, info))
        grand_total += info["amount"]

    out = ["🛡️ <b>ADMIN HOLD</b>\n"]
    for admin, deals in admin_groups.items():
        admin_total = sum(d[1]["amount"] for d in deals)
        out.append(f"🛡️ <b>{admin}</b> — Total Hold: ₹{admin_total:,.2f}")
        for did, d in deals:
            amt = d["amount"]
            fee, rate, _, net = get_fee(amt)
            b_tag = d["buyer"].split()[0] if d["buyer"] else "@Buyer"
            s_tag = d["seller"].split()[0] if d["seller"] else "@Seller"
            out.append(f"  • <b>{did}</b> — ₹{amt:,.2f}\n    Buyer: {b_tag}\n    Seller: {s_tag}\n    Fee: {rate} — Net: ₹{net:,.2f}\n    Detail: {d.get('details', 'N/A')}")
        out.append("")

    out.append("──────────────────")
    out.append(f"🛡️ <b>ALL ADMINS TOTAL HOLD: ₹{grand_total:,.2f}</b>")
    await u.message.reply_text("\n".join(out), parse_mode="HTML")

async def handle_txt(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not u.message or not u.message.text: return
    t = u.message.text.strip()
    tl = t.lower()
    
    if tl in ["form", ".form"]: await form(u, c); return
    elif tl in ["fees", "fee", ".fee", ".fees"]: await fee_command(u, c); return
    elif tl in ["adminhold", ".adminhold"]: await admin_hold_cmd(u, c); return

    fee_match = re.match(r"^(?:fee|fees|\.fee|\.fees|\/fee|\/fees)\s+([^\s]+)", tl)
    if fee_match:
        amt = parse_amt(fee_match.group(1))
        if amt > 0: await send_fee_result(u, amt); return

if __name__ == '__main__':
    threading.Thread(target=run_web, daemon=True).start()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("form", form))
    app.add_handler(CommandHandler("fee", fee_command))
    app.add_handler(CommandHandler("fees", fee_command))
    app.add_handler(CommandHandler("deal", start_deal))
    app.add_handler(CommandHandler("close", close_deal))
    app.add_handler(CommandHandler("hold", hold_deal))
    app.add_handler(CommandHandler("cancel", cancel_deal))
    app.add_handler(CommandHandler("refund", refund_deal))
    app.add_handler(CommandHandler("status", status_deal))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("adminhold", admin_hold_cmd))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_txt))
    
    app.run_polling(drop_pending_updates=True)
        

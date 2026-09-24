import os, re, random, unicodedata, threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

web_app = Flask(__name__)
@web_app.route('/')
def home(): return "Bot Running 24/7"

def run_web():
    web_app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

BOT_TOKEN = "8938665546:AAGvZElRJ36ji3LP7qyG4W90vC2ZFIQRKJY"
OWNER_ID = 7364435907
PROOF_CHANNEL = ""

DEALS_DB = {}
STATS = {"total_deals": 0, "total_volume": 0.0, "total_fees": 0.0}

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid == OWNER_ID: return True
    try:
        admins = await context.bot.get_chat_administrators(update.effective_chat.id)
        return any(a.user.id == uid for a in admins)
    except: return False

def norm_txt(t):
    t = unicodedata.normalize('NFKD', t)
    for k, v in {'ꜱ':'s','ᴇ':'e','ʟ':'l','ʀ':'r','ʙ':'b','ᴜ':'u','ʏ':'y','ᴅ':'d','ᴀ':'a','ᴛ':'t','ɪ':'i','ᴏ':'o','ᴡ':'w'}.items():
        t = t.replace(k, v)
    return t

def get_fee(amt):
    if amt <= 190: f, r, d = 10.0, "Flat ₹10", "Rs 10"
    elif amt <= 599: f, r, d = 20.0, "Flat ₹20", "Rs 20"
    elif amt <= 2000: f, r, d = round(amt*0.035, 2), "3.5%", f"3.5% - {round(amt*0.035):,.0f}₹"
    else: f, r, d = round(amt*0.03, 2), "3%", f"3% - {round(amt*0.03):,.0f}₹"
    return f, r, d, amt - f

def parse_amt(val):
    if not val: return 0.0
    c = val.lower().replace("₹","").replace(",","").replace("rs","").strip()
    m = re.search(r"(\d+(\.\d+)?)(\s*k)?", c)
    if not m: return 0.0
    n = float(m.group(1))
    return n * 1000 if m.group(3) else n

def extract_f(t):
    n = norm_txt(t)
    f = {"seller": "", "buyer": "", "details": "", "amount": "", "till": "SECURE", "deal_id": ""}
    im = re.search(r"(?:deal\s*id|trade\s*id)\s*[:\-]?\s*([A-Za-z0-9\-]+)", n, re.I)
    if im: f["deal_id"] = im.group(1).strip()
    for l in n.splitlines():
        m = re.match(r"^[•\-\*\s]*(seller|buyer|deal\s*details|deal\s*deatails|details|deal\s*amount|amount|escrow\s*till|till)\s*[:\-]\s*(.*)$", l.strip(), re.I)
        if m:
            k, v = m.group(1).lower().replace(" ",""), m.group(2).strip()
            if "seller" in k and not f["seller"]: f["seller"] = v
            elif "buyer" in k and not f["buyer"]: f["buyer"] = v
            elif "detail" in k and not f["details"]: f["details"] = v
            elif "amount" in k and not f["amount"]: f["amount"] = v
            elif "till" in k and v: f["till"] = v
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
            "📱 <b>RG :</b> @CHIKUNXT\n━━━━━━━━━━━━━━━━━━━\n💡 Check amount: <code>/fee 2000</code>",
            parse_mode="HTML"
        )
        return
    amt = parse_amt(c.args[0])
    if amt <= 0:
        await u.message.reply_text("❌ Sahi amount likhein (e.g. <code>/fee 1500</code>)!", parse_mode="HTML")
        return
    fee, rate, dsp, rcv = get_fee(amt)
    await u.message.reply_text(
        f"📊 <b>@CHIKUESCROWSERVICE FEE CALCULATOR</b>\n━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Deal Amount:</b> ₹{amt:,.0f}\n⚡ <b>Fee Rate:</b> {rate}\n💵 <b>Escrow Fee:</b> ₹{fee:,.0f}\n"
        f"━━━━━━━━━━━━━━━━━━━\n✅ <b>Seller Receives:</b> ₹{rcv:,.0f}\n\n📱 <b>RG :</b> @CHIKUNXT",
        parse_mode="HTML"
    )

async def start_deal(u: Update, c: ContextTypes.DEFAULT_TYPE):
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
    did = f"DL-CHIKU-{random.randint(1000, 9999)}"
    eu = u.effective_user
    DEALS_DB[did] = {"status": "ACTIVE", "seller": s_fmt, "buyer": b_fmt, "amount": amt_num, "fee": fee_num, "escrower": eu.first_name}
    slip = (
        f"<b>ESCROW DEAL</b>\n🪪 <b>DEAL ID:</b> {did}\n\n• <b>ꜱᴇʟʟᴇʀ :</b> {s_fmt}\n• <b>ʙᴜʏᴇʀ  :</b> {b_fmt}\n\n"
        f"• <b>ᴅᴇᴀʟ ᴅᴇᴀᴛᴀɪʟꜱ :</b> {f['details'] or 'N/A'}\n• <b>ᴅᴇᴀʟ ᴀᴍᴏᴜɴᴛ :</b> {f['amount'] or 'N/A'}\n"
        f"• <b>ᴇꜱᴄʀᴏᴡ ᴛɪʟʟ :</b> {f['till']}\n\n<b>Escrower :</b> {eu.mention_html()} ({eu.id}){fee_line}"
    )
    sm = await c.bot.send_message(chat_id=u.effective_chat.id, text=slip, parse_mode="HTML")
    try: await c.bot.pin_chat_message(chat_id=u.effective_chat.id, message_id=sm.message_id)
    except: pass

async def close_deal(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(u, c):
        await u.message.reply_text("❌ Sirf escrow admin yeh command chala sakta hai.")
        return
    amt_str, buyer, seller, did = "", "", "", None
    rep = u.message.reply_to_message
    if rep and (rep.text or rep.caption):
        n = norm_txt(rep.text or rep.caption)
        dm = re.search(r"(?:deal\s*id|trade\s*id)\s*[:\-]?\s*(DL-CHIKU-[0-9]+)", n, re.I)
        if dm: did = dm.group(1).upper()
        sm = re.search(r"seller\s*[:\-]\s*(@?[A-Za-z0-9_]+)", n, re.I)
        bm = re.search(r"buyer\s*[:\-]\s*(@?[A-Za-z0-9_]+)", n, re.I)
        if sm: seller = sm.group(1).strip() if sm.group(1).strip().startswith("@") else f"@{sm.group(1).strip()}"
        if bm: buyer = bm.group(1).strip() if bm.group(1).strip().startswith("@") else f"@{bm.group(1).strip()}"
        am = re.search(r"(?:deal amount|amount)\s*[:\-]\s*([^\n\r]+)", n, re.I)
        if am: amt_str = am.group(1).strip()
    if len(c.args) >= 1 and not amt_str: amt_str = c.args[0]
    if len(c.args) >= 2 and not buyer: buyer = c.args[1]
    if len(c.args) >= 3 and not seller: seller = c.args[2]
    amt_num = parse_amt(amt_str)
    if amt_num <= 0 or not buyer or not seller:
        await u.message.reply_text("⚠️ Deal slip ka <b>Reply</b> karke <code>/close</code> likhein!", parse_mode="HTML")
        return
    eu = u.effective_user
    etag = f"@{eu.username}" if eu.username else eu.mention_html()
    tid = did if did else f"DL-CHIKU-{random.randint(1000, 9999)}"
    fee_num, _, _, _ = get_fee(amt_num)
    STATS["total_deals"] += 1
    STATS["total_volume"] += amt_num
    STATS["total_fees"] += fee_num
    if tid in DEALS_DB: DEALS_DB[tid]["status"] = "COMPLETED"
    txt = (
        f"✅ <b>Deal Completed</b>\n🪪 <b>Trade ID:</b>\n{tid}\n📤 <b>Released:</b> ₹{amt_num:,.2f}\n"
        f"👤 <b>Escrowed By:</b>\n{etag}\n\n~ {buyer} and {seller}\nare requested to drop the\n"
        f"vouch before leaving 👇🏻\n\n<code>Vouch @chikuescrowservice for ₹{amt_num:,.2f} smooth escrow deal</code>"
    )
    sm = await c.bot.send_message(chat_id=u.effective_chat.id, text=txt, parse_mode="HTML")
    try: await c.bot.pin_chat_message(chat_id=u.effective_chat.id, message_id=sm.message_id)
    except: pass
    if PROOF_CHANNEL:
        try: await c.bot.send_message(chat_id=PROOF_CHANNEL, text=txt, parse_mode="HTML")
        except: pass

async def cancel_deal(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(u, c): return
    rep = u.message.reply_to_message
    if not rep or not (rep.text or rep.caption):
        await u.message.reply_text("⚠️ Deal slip ka <b>Reply</b> karke <code>/cancel</code> likhein!", parse_mode="HTML")
        return
    rsn = " ".join(c.args) if c.args else "Mutual Agreement"
    dm = re.search(r"(?:deal\s*id|trade\s*id)\s*[:\-]?\s*([A-Za-z0-9\-]+)", norm_txt(rep.text or rep.caption), re.I)
    did = dm.group(1).upper() if dm else "UNKNOWN"
    if did in DEALS_DB: DEALS_DB[did]["status"] = "CANCELLED"
    txt = f"❌ <b>DEAL CANCELLED</b>\n━━━━━━━━━━━━━━━━━━━\n🪪 <b>Deal ID:</b> {did}\n⚠️ <b>Reason:</b> {rsn}\n👤 <b>Action By:</b> {u.effective_user.mention_html()}"
    sm = await u.message.reply_text(txt, parse_mode="HTML")
    try: await c.bot.pin_chat_message(chat_id=u.effective_chat.id, message_id=sm.message_id)
    except: pass

async def refund_deal(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(u, c): return
    rep = u.message.reply_to_message
    if not rep or not (rep.text or rep.caption):
        await u.message.reply_text("⚠️ Deal slip ka <b>Reply</b> karke <code>/refund</code> likhein!", parse_mode="HTML")
        return
    f = extract_f(rep.text or rep.caption)
    txt = (
        f"↩️ <b>ESCROW REFUND PROCESSED</b>\n━━━━━━━━━━━━━━━━━━━\n🪪 <b>Deal ID:</b> {f['deal_id'] or 'N/A'}\n"
        f"👤 <b>Refund To:</b> {f['buyer'] or 'Buyer'}\n💰 <b>Amount:</b> ₹{parse_amt(f['amount']):,.0f}\n"
        f"👤 <b>Escrower:</b> {u.effective_user.mention_html()}\n\n⚠️ <i>Escrow fees non-refundable as per policy.</i>"
    )
    sm = await u.message.reply_text(txt, parse_mode="HTML")
    try: await c.bot.pin_chat_message(chat_id=u.effective_chat.id, message_id=sm.message_id)
    except: pass

async def status_deal(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not c.args:
        await u.message.reply_text("⚠️ Deal ID likhein! e.g. <code>/status DL-CHIKU-1234</code>", parse_mode="HTML")
        return
    did = c.args[0].upper().strip()
    if did not in DEALS_DB:
        await u.message.reply_text(f"❓ Deal ID <code>{did}</code> record me nahi mili.", parse_mode="HTML")
        return
    d = DEALS_DB[did]
    bdg = "🟢" if d["status"] == "ACTIVE" else ("✅" if d["status"] == "COMPLETED" else "❌")
    await u.message.reply_text(f"🔍 <b>DEAL STATUS</b>\n🪪 <b>ID:</b> {did}\n📌 <b>Status:</b> {bdg} {d['status']}\n💰 <b>Amount:</b> ₹{d['amount']:,.0f}\n👤 <b>Seller:</b> {d['seller']}\n👤 <b>Buyer:</b> {d['buyer']}", parse_mode="HTML")

async def stats_cmd(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(
        f"📈 <b>@CHIKUESCROWSERVICE STATS</b>\n━━━━━━━━━━━━━━━━━━━\n"
        f"🤝 <b>Total Deals:</b> {STATS['total_deals']}\n💼 <b>Total Volume:</b> ₹{STATS['total_volume']:,.2f}\n"
        f"💵 <b>Total Fees:</b> ₹{STATS['total_fees']:,.2f}",
        parse_mode="HTML"
    )

async def handle_txt(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not u.message or not u.message.text: return
    t = u.message.text.strip().lower()
    if t in ["form", ".form"]: await form(u, c); return
    elif t in ["fees", "fee", ".fee", ".fees"]: await fee_command(u, c); return
    elif t in ["close", ".close"]: await close_deal(u, c); return
    if u.effective_chat.type in ["group", "supergroup"]:
        if not await is_admin(u, c):
            fn = ((u.effective_user.first_name or "") + " " + (u.effective_user.last_name or "")).lower()
            un = (u.effective_user.username or "").lower()
            if any(k in fn or k in un for k in ["chikunxt", "harshal", "chiku escrow"]):
                await u.message.reply_text(f"🚨 <b>FAKE ADMIN ALERT!</b>\n⚠️ {u.effective_user.mention_html()} real admin nahi hai!\n👉 Real: @CHIKUNXT (<code>{OWNER_ID}</code>)", parse_mode="HTML")

if __name__ == '__main__':
    threading.Thread(target=run_web, daemon=True).start()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("form", form))
    app.add_handler(CommandHandler("fee", fee_command))
    app.add_handler(CommandHandler("fees", fee_command))
    app.add_handler(CommandHandler("deal", start_deal))
    app.add_handler(CommandHandler("close", close_deal))
    app.add_handler(CommandHandler("cancel", cancel_deal))
    app.add_handler(CommandHandler("refund", refund_deal))
    app.add_handler(CommandHandler("status", status_deal))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_txt))
    app.run_polling()

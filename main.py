import os
import re
import unicodedata
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Chiku Escrow Active 24/7"

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8938665546:AAHnBE3UDHwj501WbSNF0ZeKq0dnVqz7TZM")
OWNER_ID = 7364435907
DEALS_DB = {}
STATS = {"deals": 0, "vol": 0.0, "fees": 0.0}
DEAL_CTR, CURR_DEAL, LAST_PIN = 11254, None, None
ADMINS_LIST = {OWNER_ID}
CO_OWNERS = set()

async def is_admin(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not u.effective_user:
        return False
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
    if not t:
        return ""
    norm = unicodedata.normalize('NFKD', str(t))
    return "".join(MAP.get(ch, ch) for ch in norm).lower()

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
    if amt <= 3000:
        f = round(amt * 0.03, 2)
        return f, "3%", f"3% - {round(f)}₹", amt - f
    f = round(amt * 0.03, 2)
    return f, "3%", f"3% - {round(f)}₹", amt - f

def parse_form(raw):
    d = {"seller": "", "buyer": "", "details": "", "amount": 0.0, "till": "", "id": ""}
    if not raw:
        return d
    c_full = clean_txt(raw)
    m_id = re.search(r"dl[-_ ]*chiku[-_ ]*(\d+)", c_full, re.I)
    if m_id:
        d["id"] = f"DL-CHIKU-{m_id.group(1)}"
    
    r_lines = raw.split('\n')
    c_lines = c_full.split('\n')
    for i, (r_l, c_l) in enumerate(zip(r_lines, c_lines)):
        if not c_l.strip():
            continue
        val = r_l.split(':', 1)[1].strip() if ':' in r_l else (r_l.split('-', 1)[1].strip() if '-' in r_l else "")
        lbl = re.sub(r'^[•\*\-\s]+', '', c_l.split(':', 1)[0] if ':' in c_l else c_l.split('-', 1)[0]).strip()
        
        if (lbl in ['seller', 's'] or lbl.endswith(' seller')) and not d['seller']:
            d['seller'] = val
        elif (lbl in ['buyer', 'b'] or lbl.endswith(' buyer')) and not d['buyer']:
            d['buyer'] = val
        elif any(k in lbl for k in ['detail', 'deatail']) and not d['details']:
            d['details'] = val
        elif any(k in lbl for k in ['amount', 'amt', 'price', 'cost']) and d['amount'] == 0.0:
            m = re.search(r'(\d+(?:\.\d+)?)', clean_txt(val).replace(',', ''))
            if m:
                d['amount'] = float(m.group(1))
        elif 'till' in lbl and not d['till']:
            d['till'] = val
    return d

async def resolve_u(u, rep, ctx, cid):
    if not u or u.upper() == "N/A":
        return u or "N/A"
    clean = u.strip()
    if clean.isdigit():
        return f'<a href="tg://user?id={clean}">{clean}</a> ({clean})'
    if clean.lower() in ["me", "i", "myself", "mai"] and rep and rep.from_user:
        fu = rep.from_user
        return f"@{fu.username} ({fu.id})" if fu.username else f"{fu.first_name} ({fu.id})"
    return clean

async def del_m(u: Update):
    try:
        if u.message:
            await u.message.delete()
    except:
        pass

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
            "👋 Welcome Harshal! Aap yahan se bot ko manage aur configure kar sakte hain.",
            parse_mode="HTML"
        )
    else:
        msg = (
            "🛡️ <b>CHIKU ESCROW</b>\n\n"
            "👋 Welcome to Chiku Escrow!\n\n"
            "🔐 Secure Escrow Service\n"
            "💰 Transparent Fee System\n"
            "🤝 Safe Deal Management\n\n"
            "If you need escrow assistance, please contact @CHIKUNXT."
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
        "/chatid — Chat ID"
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
        await u.message.reply_text("⚠️ Owner / Co-Owner only command!")
        return
    if c.args and c.args[0].isdigit():
        DEAL_CTR = int(c.args[0])
        await u.message.reply_text(f"✅ Trade ID counter set to: DL-CHIKU-{DEAL_CTR}")
    else:
        await u.message.reply_text("💡 Use: <code>/settradeid 198</code>", parse_mode="HTML")

async def cmd_minus(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(u, c):
        return
    if DEALS_DB:
        last_key = list(DEALS_DB.keys())[-1]
        del DEALS_DB[last_key]
        await u.message.reply_text(f"🗑️ Latest deal record ({last_key}) removed successfully.")
    else:
        await u.message.reply_text("⚠️ No active deals to remove.")

async def cmd_unhold(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global LAST_PIN
    await del_m(u)
    if not await is_admin(u, c):
        return
    if CURR_DEAL in DEALS_DB:
        DEALS_DB[CURR_DEAL]["status"] = "ACTIVE"
    if LAST_PIN:
        try:
            await c.bot.unpin_chat_message(chat_id=u.effective_chat.id, message_id=LAST_PIN)
        except:
            pass
    sm = await c.bot.send_message(chat_id=u.effective_chat.id, text=f"🔓 <b>DEAL UNHOLD / RESUMED</b>\n🪪 <b>ID:</b> {CURR_DEAL or 'DL-ACTIVE'}", parse_mode="HTML")
    await safe_pin(c, u.effective_chat.id, sm.message_id)
    LAST_PIN = sm.message_id

async def cmd_earnings(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(u, c):
        return
    await u.message.reply_text(f"📊 <b>Total Earnings / Fees:</b> ₹{STATS['fees']:,.2f}", parse_mode="HTML")

async def cmd_report(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(u, c):
        return
    await u.message.reply_text(f"📋 <b>Deal Report Summary:</b>\nTotal Deals: {STATS['deals']}\nVolume: ₹{STATS['vol']:,.2f}\nFees: ₹{STATS['fees']:,.2f}", parse_mode="HTML")

async def cmd_stats(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(f"📈 <b>@CHIKUESCROWSERVICE STATS</b>\n━━━━━━━━━━━━━━━━━━━\n🤝 <b>Total Deals:</b> {STATS['deals']}\n💼 <b>Total Volume:</b> ₹{STATS['vol']:,.2f}\n💵 <b>Total Fees:</b> ₹{STATS['fees']:,.2f}\n📱 <b>RG :</b> @CHIKUNXT", parse_mode="HTML")

async def cmd_coowneradd(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not u.effective_user or u.effective_user.id != OWNER_ID:
        await u.message.reply_text("⚠️ Owner only command!")
        return
    if c.args and c.args[0].isdigit():
        uid = int(c.args[0])
        CO_OWNERS.add(uid)
        await u.message.reply_text(f"✅ Co-Owner ID {uid} added.")
    else:
        await u.message.reply_text("💡 Use: <code>/coowneradd 123456789</code>", parse_mode="HTML")

async def cmd_coownerremove(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not u.effective_user or u.effective_user.id != OWNER_ID:
        await u.message.reply_text("⚠️ Owner only command!")
        return
    if c.args and c.args[0].isdigit():
        uid = int(c.args[0])
        if uid in CO_OWNERS:
            CO_OWNERS.remove(uid)
        await u.message.reply_text(f"✅ Co-Owner ID {uid} removed.")
    else:
        await u.message.reply_text("💡 Use: <code>/coownerremove 123456789</code>", parse_mode="HTML")

async def cmd_coowners(u: Update, c: ContextTypes.DEFAULT_TYPE):
    lst = ", ".join(str(i) for i in CO_OWNERS) if CO_OWNERS else "None"
    await u.message.reply_text(f"👑 <b>Co-Owners List:</b>\n<code>{lst}</code>", parse_mode="HTML")

async def cmd_settings(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(u, c):
        return
    await u.message.reply_text("⚙️ <b>Bot Settings Panel:</b>\nAll systems are fully functional and secure under @CHIKUNXT.", parse_mode="HTML")

async def cmd_fee(u: Update, c: ContextTypes.DEFAULT_TYPE):
    fee_text = (
        "<b>@CHIKUESCROWSERVICE CHARGES -</b>\n\n"
        "• <b>Under ₹190 - ₹10</b>\n"
        "• <b>₹191 To ₹599 - ₹20</b>\n"
        "• <b>₹600 To ₹2000 - 3.5%</b>\n"
        "• <b>₹2001 To ₹3000 - 3%</b>\n"
        "• <b>Upper Than ₹3000 - 3%</b>\n\n"
        "📱 <b>RG : @CHIKUNXT</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "💡 <b>Check:</b> <code>fees 2000</code>"
    )
    await u.message.reply_text(fee_text, parse_mode="HTML")

async def cmd_addadmin(u: Update, c: ContextTypes.DEFAULT_TYPE):
    uid = u.effective_user.id if u.effective_user else 0
    if uid != OWNER_ID and uid not in CO_OWNERS:
        await u.message.reply_text("⚠️ Owner / Co-Owner only command!")
        return
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
        await u.message.reply_text("⚠️ Owner / Co-Owner only command!")
        return
    if c.args and c.args[0].isdigit():
        uid_to_rem = int(c.args[0])
        if uid_to_rem in ADMINS_LIST:
            ADMINS_LIST.remove(uid_to_rem)
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
    if not await is_admin(u, c):
        return
    rep = u.message.reply_to_message
    if not rep or not (rep.text or rep.caption):
        await u.message.reply_text("⚠️ Bhare hue <b>FORM</b> ka reply karke <code>/deal</code> bhejo!", parse_mode="HTML")
        return
    if LAST_PIN:
        try:
            await c.bot.unpin_chat_message(chat_id=u.effective_chat.id, message_id=LAST_PIN)
        except:
            pass
    f = parse_form(rep.text or rep.caption)
    if c.args:
        n = re.sub(r'[^\d\.]', '', c.args[0])
        if n:
            f["amount"] = float(n)
    did = f"DL-CHIKU-{DEAL_CTR}"
    DEAL_CTR += 1
    CURR_DEAL = did
    eu = u.effective_user
    amt = f["amount"]
    msg = f"<b>ESCROW DEAL</b>\n🪪 <b>DEAL ID:</b> {did}\n\n• <b>ꜱᴇʟʟᴇʀ :</b> {f['seller'] or 'N/A'}\n• <b>ʙᴜʏᴇʀ  :</b> {f['buyer'] or 'N/A'}\n\n• <b>ᴅᴇᴀʟ ᴀᴍᴏᴜɴᴛ :</b> ₹{amt:,.0f}\n\n<b>Escrower :</b> {eu.mention_html()}"
    sm = await c.bot.send_message(chat_id=u.effective_chat.id, text=msg, parse_mode="HTML")
    await safe_pin(c, u.effective_chat.id, sm.message_id)
    LAST_PIN = sm.message_id
    DEALS_DB[did] = {"status": "ACTIVE", "amount": amt, "msg_id": sm.message_id}

async def cmd_close(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global CURR_DEAL, LAST_PIN
    await del_m(u)
    if not await is_admin(u, c):
        return
    did = CURR_DEAL or "DL-CHIKU-11254"
    if did in DEALS_DB:
        DEALS_DB[did]["status"] = "COMPLETED"
    STATS["deals"] += 1
    if LAST_PIN:
        try:
            await c.bot.unpin_chat_message(chat_id=u.effective_chat.id, message_id=LAST_PIN)
        except:
            pass
    text = "✅ DEAL COMPLETED\nID: " + did + "\nSuccessfully closed by " + (u.effective_user.first_name if u.effective_user else "Admin")
    sm = await c.bot.send_message(chat_id=u.effective_chat.id, text=text)
    await safe_pin(c, u.effective_chat.id, sm.message_id)
    LAST_PIN = sm.message_id

async def cmd_hold(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global LAST_PIN
    await del_m(u)
    if not await is_admin(u, c):
        return
    did = CURR_DEAL or "DL-CHIKU-11254"
    if did in DEALS_DB:
        DEALS_DB[did]["status"] = "ON HOLD"
    rsn = " ".join(c.args) if c.args else "Verification / Dispute Under Review"
    text = "⏳ DEAL ON HOLD\nID: " + did + "\nReason: " + rsn
    sm = await c.bot.send_message(chat_id=u.effective_chat.id, text=text)
    await safe_pin(c, u.effective_chat.id, sm.message_id)
    LAST_PIN = sm.message_id

async def cmd_refund(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global LAST_PIN
    await del_m(u)
    if not await is_admin(u, c):
        return
    did = CURR_DEAL or "DL-CHIKU-11254"
    if did in DEALS_DB:
        DEALS_DB[did]["status"] = "REFUNDED"
    text = "🔄 DEAL REFUNDED\nID: " + did + "\nAmount refunded safely to buyer."
    sm = await c.bot.send_message(chat_id=u.effective_chat.id, text=text)
    await safe_pin(c, u.effective_chat.id, sm.message_id)
    LAST_PIN = sm.message_id

async def cmd_cancel(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global LAST_PIN
    await del_m(u)
    if not await is_admin(u, c):
        return
    did = CURR_DEAL or "DL-CHIKU-11254"
    if did in DEALS_DB:
        DEALS_DB[did]["status"] = "CANCELLED"
    user_name = u.effective_user.first_name if u.effective_user else "Admin"
    text = "❌ DEAL CANCELLED\nID: " + did + "\nBy: " + user_name
    sm = await c.bot.send_message(chat_id=u.effective_chat.id, text=text)
    await safe_pin(c, u.effective_chat.id, sm.message_id)
    LAST_PIN = sm.message_id

async def cmd_form(u: Update, c: ContextTypes.DEFAULT_TYPE):
    msg = (
        "<b>ᴇꜱᴄʀᴏᴡ ᴅᴇᴀʟ ғᴏʀᴍ</b>\n\n"
        "• <b>ꜱᴇʟʟᴇʀ :</b> \n\n"
        "• <b>ʙᴜʏᴇʀ :</b> \n\n"
        "• <b>ᴅᴇᴀʟ ᴅᴇᴀᴛᴀɪʟꜱ :</b> \n\n"
        "• <b>ᴅᴇᴀʟ ᴀᴍᴏᴜɴᴛ :</b> \n\n"
        "• <b>ᴇꜱᴄʀᴏᴡ ᴛɪʟʟ :</b> \n\n"
        "• <b>ғᴏʀ ʀᴇʟᴇᴀsᴇ sᴇʟʟᴇʀ ᴜ𝚙ɪ :</b> \n\n"
        "<i>ғᴏʀ ᴍᴏʀᴇ ᴘʀᴏᴏғs ᴄʜᴇᴄᴋ ɢʀᴏᴜᴘ ᴘɪɴ ᴍᴇssᴀɢᴇs..</i>\n\n"
        "⚠️ <b>ESCROW FEES IS NON - REFUNDABLE NO MATTER IF THE DEAL GETS CANCELLED</b> ⚠️"
    )
    await u.message.reply_text(msg, parse_mode="HTML")

async def text_router(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not u.message or not u.message.text:
        return
    t = u.message.text.strip().lower()
    
    # Exact check for fee/fees without amount
    if t in ["fee", "fees", ".fee", ".fees", "/fee", "/fees"]:
        await cmd_fee(u, c)
        return
    elif t in ["form", ".form", "/form"]:
        await cmd_form(u, c)
        return
    elif t in ["stats", ".stats", "/stats"]:
        await cmd_stats(u, c)
        return
    elif t in ["refund", ".refund"]:
        await cmd_refund(u, c)
        return

    # Check for fee calculation with amount (e.g. fees 2000, /fees 2000)
    m = re.match(r"^(?:\/)?(?:fee|fees|\.fee|\.fees)\s+(\d+(?:\.\d+)?)", t)
    if m:
        num_str = m.group(1)
        if num_str:
            amt = float(num_str)
            fee, rate, _, rcv = calc_fee(amt)
            await u.message.reply_text(f"📊 <b>@CHIKUESCROWSERVICE FEE CALCULATOR</b>\n━━━━━━━━━━━━━━━━━━━\n💰 <b>Deal Amount:</b> ₹{amt:,.0f}\n⚡ <b>Fee Rate:</b> {rate}\n💵 <b>Escrow Fee:</b> ₹{fee:,.0f}\n━━━━━━━━━━━━━━━━━━━\n✅ <b>Seller Receives:</b> ₹{rcv:,.0f}\n\n📱 <b>RG :</b> @CHIKUNXT", parse_mode="HTML")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("c", cmd_c))
    app.add_handler(CommandHandler("settradeid", cmd_settradeid))
    app.add_handler(CommandHandler("minus", cmd_minus))
    app.add_handler(CommandHandler("unhold", cmd_unhold))
    app.add_handler(CommandHandler("earnings", cmd_earnings))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("coowneradd", cmd_coowneradd))
    app.add_handler(CommandHandler("coownerremove", cmd_coownerremove))
    app.add_handler(CommandHandler("coowners", cmd_coowners))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("fee", cmd_fee))
    app.add_handler(CommandHandler("fees", cmd_fee))
    app.add_handler(CommandHandler("addadmin", cmd_addadmin))
    app.add_handler(CommandHandler("removeadmin", cmd_removeadmin))
    app.add_handler(CommandHandler("admins", cmd_admins))
    app.add_handler(CommandHandler("chatid", cmd_chatid))
    
    app.add_handler(CommandHandler("form", cmd_form))
    app.add_handler(CommandHandler("deal", cmd_deal))
    app.add_handler(CommandHandler("close", cmd_close))
    app.add_handler(CommandHandler("hold", cmd_hold))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("refund", cmd_refund))
    app.add_handler(CommandHandler("stats", cmd_stats))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    
    port = int(os.environ.get("PORT", 10000))
    import threading
    threading.Thread(target=lambda: web_app.run(host='0.0.0.0', port=port), daemon=True).start()
    
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()

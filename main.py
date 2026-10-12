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
    if amt <= 100:
        return 10.0, "Flat ₹10", "Rs 10", amt - 10.0
    if amt <= 599:
        return 20.0, "Flat ₹20", "Rs 20", amt - 20.0
    if amt <= 2000:
        f = round(amt * 0.035, 2)
        return f, "3.5%", f"3.5% - {round(f)}₹", amt - f
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
            "If you need escrow assistance, please contact @HARSHALxNXT."
        )
        await u.message.reply_text(msg, parse_mode="HTML")

async def cmd_help(u: Update, c: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🛡️ <b>CHIKU ESCROW — ADMIN COMMANDS</b>\n\n"
        "/deal [amount] — Add escrow deal\n"
        "/close — Close your own deal\n"
        "/hold [Reason] — Hold your own deal\n"
        "/unhold — Remove hold\n"
        "/cancel — Cancel your own deal\n"
        "/refund — Refund your own deal\n"
        "/c [amount] — 💎 Public Fee Calculator"
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

async def cmd_deal(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global DEAL_CTR, CURR_DEAL, LAST_PIN
    if not await is_admin(u, c):
        return
    rep = u.message.reply_to_message
    if not rep or not (rep.text or rep.caption):
        await u.message.reply_text("⚠️ Bhare hue <b>FORM</b> ka reply karke <code>/deal</code> bhejo!", parse_mode="HTML")
        return
    f = parse_form(rep.text or rep.caption)
    did = f"DL-CHIKU-{DEAL_CTR}"
    DEAL_CTR += 1
    CURR_DEAL = did
    eu = u.effective_user
    msg = f"<b>ESCROW DEAL</b>\n🪪 <b>DEAL ID:</b> {did}\n\n• <b>ꜱᴇʟʟᴇʀ :</b> {f['seller'] or 'N/A'}\n• <b>ʙᴜʏᴇʀ  :</b> {f['buyer'] or 'N/A'}\n\n• <b>ᴅᴇᴀʟ ᴀᴍᴏᴜɴᴛ :</b> ₹{f['amount']:,.0f}\n\n<b>Escrower :</b> {eu.mention_html()}"
    sm = await c.bot.send_message(chat_id=u.effective_chat.id, text=msg, parse_mode="HTML")
    await safe_pin(c, u.effective_chat.id, sm.message_id)
    LAST_PIN = sm.message_id
    DEALS_DB[did] = {"status": "ACTIVE", "amount": f['amount'], "msg_id": sm.message_id}

async def cmd_cancel(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global LAST_PIN
    await del_m(u)
    if not await is_admin(u, c):
        return
    did = CURR_DEAL or "DL-CHIKU-11254"
    user_name = u.effective_user.first_name if u.effective_user else "Admin"
    text = "DEAL CANCELLED\nID: " + did + "\nBy: " + user_name
    sm = await c.bot.send_message(chat_id=u.effective_chat.id, text=text)
    await safe_pin(c, u.effective_chat.id, sm.message_id)
    LAST_PIN = sm.message_id

async def cmd_form(u: Update, c: ContextTypes.DEFAULT_TYPE):
    msg = "<b>ᴇꜱᴄʀᴏᴡ ᴅᴇᴀʟ ғᴏʀᴍ</b>\n\n• <b>ꜱᴇʟʟᴇʀ :</b> \n\n• <b>ʙᴜʏᴇʀ :</b> \n\n• <b>ᴅᴇᴀʟ ᴅᴇᴀᴛᴀɪʟꜱ :</b> \n\n• <b>ᴅᴇᴀʟ ᴀᴍᴏᴜɴᴛ :</b> \n\n• <b>ᴇꜱᴄʀᴏᴡ ᴛɪʟʟ :</b>"
    await u.message.reply_text(msg, parse_mode="HTML")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("c", cmd_c))
    app.add_handler(CommandHandler("deal", cmd_deal))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("form", cmd_form))
    
    port = int(os.environ.get("PORT", 10000))
    # Render ke liye webhook ya polling start karne se pehle flask run hoga
    import threading
    threading.Thread(target=lambda: web_app.run(host='0.0.0.0', port=port), daemon=True).start()
    
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
        

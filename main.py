import os
import re
import random
import unicodedata
import threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Bot is running!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host='0.0.0.0', port=port)

# Bot Configuration
BOT_TOKEN = "8938665546:AAGvZElRJ36ji3LP7qyG4W90vC2ZFIQRKJY"
OWNER_ID = 7364435907

# Optional: Yahan apna Proof Channel ID ya Username daalein (e.g. "@chikuvouches" ya chat_id)
PROOF_CHANNEL = ""  # Example: "@chikuescrowservice"

# In-Memory Database for Stats & Status
DEALS_DB = {}
STATS = {
    "total_deals": 0,
    "total_volume": 0.0,
    "total_fees": 0.0
}

# Helper: Check Admin Rights
async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    if user_id == OWNER_ID:
        return True
    try:
        admins = await context.bot.get_chat_administrators(update.effective_chat.id)
        return any(admin.user.id == user_id for admin in admins)
    except Exception:
        return False

# Normalize fancy unicode fonts to plain text
def normalize_text(text: str) -> str:
    text = unicodedata.normalize('NFKD', text)
    small_caps = {
        'ꜱ': 's', 'ᴇ': 'e', 'ʟ': 'l', 'ʀ': 'r', 'ʙ': 'b', 'ᴜ': 'u',
        'ʏ': 'y', 'ᴅ': 'd', 'ᴀ': 'a', 'ᴛ': 't', 'ɪ': 'i', 'ᴏ': 'o', 'ᴡ': 'w'
    }
    for k, v in small_caps.items():
        text = text.replace(k, v)
    return text

# Fee Calculation Helper
def get_fee_breakdown(amount: float):
    if amount <= 190:
        fee = 10.0
        rate = "Flat ₹10"
        fee_display = "Rs 10"
    elif amount <= 599:
        fee = 20.0
        rate = "Flat ₹20"
        fee_display = "Rs 20"
    elif amount <= 2000:
        fee = round((amount * 0.035), 2)
        rate = "3.5%"
        fee_display = f"3.5% - {fee:,.0f}₹"
    else:
        fee = round((amount * 0.03), 2)
        rate = "3%"
        fee_display = f"3% - {fee:,.0f}₹"
    seller_receives = amount - fee
    return fee, rate, fee_display, seller_receives

def parse_amount(val_str: str) -> float:
    if not val_str:
        return 0.0
    cleaned = val_str.lower().replace("₹", "").replace(",", "").replace("rs", "").strip()
    match = re.search(r"(\d+(\.\d+)?)(\s*k)?", cleaned)
    if not match:
        return 0.0
    num = float(match.group(1))
    if match.group(3):
        num *= 1000
    return num

# Universal Extractor
def extract_fields(text: str):
    norm = normalize_text(text)
    fields = {"seller": "", "buyer": "", "details": "", "amount": "", "till": "SECURE", "deal_id": ""}
    
    id_m = re.search(r"(?:deal\s*id|trade\s*id)\s*[:\-]?\s*([A-Za-z0-9\-]+)", norm, re.IGNORECASE)
    if id_m:
        fields["deal_id"] = id_m.group(1).strip()

    for line in norm.splitlines():
        clean_l = re.sub(r'^[•\-\*\s]+', '', line).strip()
        m = re.match(r"^(seller|buyer|deal\s*details|deal\s*deatails|details|deal\s*amount|amount|escrow\s*till|till)\s*[:\-]\s*(.*)$", clean_l, re.IGNORECASE)
        if m:
            key = m.group(1).lower().replace(" ", "")
            val = m.group(2).strip()
            if "seller" in key and not fields["seller"]:
                fields["seller"] = val
            elif "buyer" in key and not fields["buyer"]:
                fields["buyer"] = val
            elif "detail" in key and not fields["details"]:
                fields["details"] = val
            elif "amount" in key and not fields["amount"]:
                fields["amount"] = val
            elif "till" in key and val:
                fields["till"] = val
    return fields

# Helper to fetch User with Numeric ID
async def resolve_user_id(user_str: str, replied_msg, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    if not user_str or user_str == "N/A":
        return "N/A"
    if "(" in user_str and ")" in user_str:
        return user_str
    clean_user = user_str.strip().replace("@", "")

    if replied_msg and replied_msg.entities:
        for entity in replied_msg.entities:
            if entity.type == "text_mention" and entity.user:
                if entity.user.username and entity.user.username.lower() == clean_user.lower():
                    return f"@{entity.user.username} ({entity.user.id})"
                elif entity.user.first_name and clean_user.lower() in entity.user.first_name.lower():
                    return f"{entity.user.mention_html()} ({entity.user.id})"
            elif entity.type == "mention":
                mention_text = replied_msg.text[entity.offset:entity.offset+entity.length].lstrip("@")
                if mention_text.lower() == clean_user.lower():
                    try:
                        m = await context.bot.get_chat_member(chat_id, f"@{mention_text}")
                        if m and m.user:
                            return f"@{mention_text} ({m.user.id})"
                    except Exception:
                        pass

    if replied_msg and replied_msg.from_user:
        u = replied_msg.from_user
        if u.username and u.username.lower() == clean_user.lower():
            return f"@{u.username} ({u.id})"

    try:
        m = await context.bot.get_chat_member(chat_id, f"@{clean_user}")
        if m and m.user:
            return f"@{clean_user} ({m.user.id})"
    except Exception:
        pass

    return f"@{clean_user}" if not user_str.startswith("@") else user_str

# 1. Blank Form Command (/form)
async def form(update: Update, context: ContextTypes.DEFAULT_TYPE):
    form_text = (
        "<b>ESCROW DEAL FORM</b>\n\n"
        "• <b>SELLER :</b> \n"
        "• <b>BUYER :</b> \n"
        "• <b>DEAL DETAILS :</b> \n"
        "• <b>DEAL AMOUNT :</b> \n"
        "• <b>ESCROW TILL :</b> SECURE\n"
        "• <b>FOR RELEASE SELLER UPI :</b> \n\n"
        "<i>FOR MORE PROOFS CHECK GROUP PIN MESSAGES..</i>\n\n"
        "⚠️ <b>ESCROW FEES IS NON-REFUNDABLE NO MATTER IF THE DEAL GETS CANCELLED</b> ⚠️"
    )
    await update.message.reply_text(form_text, parse_mode="HTML")

# 2. Fee Calculator Command (/fee or /fees)
async def fee_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        structure_text = (
            "<b>@CHIKUESCROWSERVICE CHARGES -</b>\n\n"
            "• Under ₹190 - ₹10\n"
            "• ₹191 To ₹599 - ₹20\n"
            "• ₹600 To ₹2000 - 3.5%\n"
            "• ₹2001 To ₹3000 - 3%\n"
            "• Upper Than ₹3000 - 3%\n\n"
            "📱 <b>RG :</b> @CHIKUNXT\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "💡 <i>Tip: Amount check karne ke liye:</i> <code>/fee 2000</code>"
        )
        await update.message.reply_text(structure_text, parse_mode="HTML")
        return

    amount = parse_amount(context.args[0])
    if amount <= 0:
        await update.message.reply_text("❌ Kripya sahi amount likhein (e.g. <code>/fee 1500</code>)!", parse_mode="HTML")
        return

    fee, fee_rate, fee_display, seller_receives = get_fee_breakdown(amount)
    calc_text = (
        f"📊 <b>@CHIKUESCROWSERVICE FEE CALCULATOR</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Deal Amount:</b> ₹{amount:,.0f}\n"
        f"⚡ <b>Fee Rate:</b> {fee_rate}\n"
        f"💵 <b>Escrow Fee:</b> ₹{fee:,.0f}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"✅ <b>Seller Receives:</b> ₹{seller_receives:,.0f}\n\n"
        f"📱 <b>RG :</b> @CHIKUNXT"
    )
    await update.message.reply_text(calc_text, parse_mode="HTML")

# 3. Form Reply par ESCROW DEAL Slip (/deal)
async def start_deal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ Sirf escrow admin yeh command chala sakta hai.")
        return

    replied_msg = update.message.reply_to_message
    if not replied_msg or not (replied_msg.text or replied_msg.caption):
        await update.message.reply_text(
            "⚠️ Kripya bhare hue <b>ESCROW FORM</b> ka <b>Reply</b> karke <code>/deal</code> likhein!",
            parse_mode="HTML"
        )
        return

    orig_text = replied_msg.text or replied_msg.caption
    fields = extract_fields(orig_text)

    seller_raw = fields["seller"] or "N/A"
    buyer_raw = fields["buyer"] or "N/A"
    details = fields["details"] or "N/A"
    amount_raw = fields["amount"] or "N/A"
    escrow_till = fields["till"] or "SECURE"

    seller_formatted = await resolve_user_id(seller_raw, replied_msg, context, update.effective_chat.id)
    buyer_formatted = await resolve_user_id(buyer_raw, replied_msg, context, update.effective_chat.id)

    amount_num = parse_amount(amount_raw)
    fee_num = 0.0
    if amount_num > 0:
        fee_num, _, fee_display, _ = get_fee_breakdown(amount_num)
        fee_line = f"\n\nFees {fee_display}"
    else:
        fee_line = ""

    deal_id = f"DL-CHIKU-{random.randint(1000, 9999)}"
    escrower_user = update.effective_user
    escrower_mention = escrower_user.mention_html()
    escrower_id = escrower_user.id

    # Store in Database
    DEALS_DB[deal_id] = {
        "status": "ACTIVE",
        "seller": seller_formatted,
        "buyer": buyer_formatted,
        "amount": amount_num,
        "fee": fee_num,
        "escrower": escrower_user.first_name
    }

    formatted_slip = (
        f"<b>ESCROW DEAL</b>\n"
        f"🪪 <b>DEAL ID:</b> {deal_id}\n\n"
        f"• <b>ꜱᴇʟʟᴇʀ :</b> {seller_formatted}\n"
        f"• <b>ʙᴜʏᴇʀ  :</b> {buyer_formatted}\n\n"
        f"• <b>ᴅᴇᴀʟ ᴅᴇᴀᴛᴀɪʟꜱ :</b> {details}\n"
        f"• <b>ᴅᴇᴀʟ ᴀᴍᴏᴜɴᴛ :</b> {amount_raw}\n"
        f"• <b>ᴇꜱᴄʀᴏᴡ ᴛɪʟʟ :</b> {escrow_till}\n\n"
        f"<b>Escrower :</b> {escrower_mention} ({escrower_id})"
        f"{fee_line}"
    )

    sent_msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=formatted_slip,
        parse_mode="HTML"
    )

    try:
        await context.bot.pin_chat_message(chat_id=update.effective_chat.id, message_id=sent_msg.message_id)
    except Exception as e:
        print(f"Pin error: {e}")

# 4. Short-Cut & Manual /close Command
async def close_deal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ Sirf escrow admin yeh command chala sakta hai.")
        return

    amount_str = ""
    buyer = ""
    seller = ""
    found_deal_id = None

    replied_msg = update.message.reply_to_message
    if replied_msg and (replied_msg.text or replied_msg.caption):
        raw = replied_msg.text or replied_msg.caption
        norm = normalize_text(raw)
        
        # Check Deal ID
        d_m = re.search(r"(?:deal\s*id|trade\s*id)\s*[:\-]?\s*(DL-CHIKU-[0-9]+)", norm, re.IGNORECASE)
        if d_m:
            found_deal_id = d_m.group(1).upper()

        seller_m = re.search(r"seller\s*[:\-]\s*(@?[A-Za-z0-9_]+)", norm, re.IGNORECASE)
        buyer_m = re.search(r"buyer\s*[:\-]\s*(@?[A-Za-z0-9_]+)", norm, re.IGNORECASE)
        if seller_m:
            s_val = seller_m.group(1).strip()
            seller = s_val if s_val.startswith("@") else f"@{s_val}"
        if buyer_m:
            b_val = buyer_m.group(1).strip()
            buyer = b_val if b_val.startswith("@") else f"@{b_val}"

        amt_m = re.search(r"(?:deal amount|amount)\s*[:\-]\s*([^\n\r]+)", norm, re.IGNORECASE)
        if amt_m:
            amount_str = amt_m.group(1).strip()

    if len(context.args) >= 1 and not amount_str:
        amount_str = context.args[0]
    if len(context.args) >= 2 and not buyer:
        buyer = context.args[1]
    if len(context.args) >= 3 and not seller:
        seller = context.args[2]

    amount_num = parse_amount(amount_str)
    if amount_num <= 0 or not buyer or not seller:
        await update.message.reply_text(
            "⚠️ <b>Short-cut:</b> Bot ke <b>ESCROW DEAL</b> slip ka <b>Reply</b> karke <code>/close</code> likhein.\n"
            "Ya manual likhein: <code>/close 2000 @ash_trust @knownrich</code>",
            parse_mode="HTML"
        )
        return

    amount_formatted = f"{amount_num:,.2f}"
    escrower_user = update.effective_user
    escrower_tag = f"@{escrower_user.username}" if escrower_user.username else escrower_user.mention_html()
    trade_id = found_deal_id if found_deal_id else f"DL-CHIKU-{random.randint(1000, 9999)}"

    # Update Stats
    fee_num, _, _, _ = get_fee_breakdown(amount_num)
    STATS["total_deals"] += 1
    STATS["total_volume"] += amount_num
    STATS["total_fees"] += fee_num
    if trade_id in DEALS_DB:
        DEALS_DB[trade_id]["status"] = "COMPLETED"

    message_text = (
        f"✅ <b>Deal Completed</b>\n"
        f"🪪 <b>Trade ID:</b>\n"
        f"{trade_id}\n"
        f"📤 <b>Released:</b> ₹{amount_formatted}\n"
        f"👤 <b>Escrowed By:</b>\n"
        f"{escrower_tag}\n\n"
        f"~ {buyer} and {seller}\n"
        f"are requested to drop the\n"
        f"vouch before leaving 👇🏻\n\n"
        f"<code>Vouch @chikuescrowservice for ₹{amount_formatted} smooth escrow deal</code>"
    )

    sent_msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message_text,
        parse_mode="HTML"
    )

    try:
        await context.bot.pin_chat_message(chat_id=update.effective_chat.id, message_id=sent_msg.message_id)
    except Exception as e:
        print(f"Pin error: {e}")

    # Channel Logger (Feature 2)
    if PROOF_CHANNEL:
        try:
            await context.bot.send_message(chat_id=PROOF_CHANNEL, text=message_text, parse_mode="HTML")
        except Exception as e:
            print(f"Channel log error: {e}")

# 5. Deal Cancel Command (/cancel [reason])
async def cancel_deal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ Sirf escrow admin deal cancel kar sakta hai.")
        return

    reason = " ".join(context.args) if context.args else "Mutual Agreement / Dispute"
    replied_msg = update.message.reply_to_message
    if not replied_msg or not (replied_msg.text or replied_msg.caption):
        await update.message.reply_text("⚠️ Deal slip ka <b>Reply</b> karke <code>/cancel [reason]</code> likhein!", parse_mode="HTML")
        return

    norm = normalize_text(replied_msg.text or replied_msg.caption)
    d_m = re.search(r"(?:deal\s*id|trade\s*id)\s*[:\-]?\s*([A-Za-z0-9\-]+)", norm, re.IGNORECASE)
    deal_id = d_m.group(1).upper() if d_m else "UNKNOWN"

    if deal_id in DEALS_DB:
        DEALS_DB[deal_id]["status"] = "CANCELLED"

    cancel_text = (
        f"❌ <b>DEAL CANCELLED</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🪪 <b>Deal ID:</b> {deal_id}\n"
        f"⚠️ <b>Reason:</b> {reason}\n"
        f"👤 <b>Action By:</b> {update.effective_user.mention_html()}\n\n"
        f"<i>Funds will be handled according to escrow terms.</i>"
    )

    sent_msg = await update.message.reply_text(cancel_text, parse_mode="HTML")
    try:
        await context.bot.pin_chat_message(chat_id=update.effective_chat.id, message_id=sent_msg.message_id)
    except Exception:
        pass

# 6. Refund Command (/refund [buyer_upi/notes])
async def refund_deal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ Sirf escrow admin refund process kar sakta hai.")
        return

    replied_msg = update.message.reply_to_message
    if not replied_msg or not (replied_msg.text or replied_msg.caption):
        await update.message.reply_text("⚠️ Deal slip ka <b>Reply</b> karke <code>/refund [details]</code> likhein!", parse_mode="HTML")
        return

    raw = replied_msg.text or replied_msg.caption
    fields = extract_fields(raw)
    amount_num = parse_amount(fields["amount"])
    buyer = fields["buyer"] or "Buyer"
    deal_id = fields["deal_id"] or "N/A"
    note = " ".join(context.args) if context.args else "Deal not completed"

    if deal_id in DEALS_DB:
        DEALS_DB[deal_id]["status"] = "REFUNDED"

    refund_text = (
        f"↩️ <b>ESCROW REFUND PROCESSED</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🪪 <b>Deal ID:</b> {deal_id}\n"
        f"👤 <b>Refund To:</b> {buyer}\n"
        f"💰 <b>Refund Amount:</b> ₹{amount_num:,.0f}\n"
        f"📝 <b>Note:</b> {note}\n"
        f"👤 <b>Escrower:</b> {update.effective_user.mention_html()}\n\n"
        f"⚠️ <i>Note: Escrow charges are non-refundable as per policy.</i>"
    )

    sent_msg = await update.message.reply_text(refund_text, parse_mode="HTML")
    try:
        await context.bot.pin_chat_message(chat_id=update.effective_chat.id, message_id=sent_msg.message_id)
    except Exception:
        pass

# 7. Deal Status Tracker (/status <deal_id>)
async def status_deal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Deal ID daalein!\nExample: <code>/status DL-CHIKU-1234</code>", parse_mode="HTML")
        return

    deal_id = context.args[0].upper().strip()
    if deal_id not in DEALS_DB:
        await update.message.reply_text(f"❓ <b>Deal ID <code>{deal_id}</code> record mein nahi mili.</b>", parse_mode="HTML")
        return

    d = DEALS_DB[deal_id]
    badge = "🟢" if d["status"] == "ACTIVE" else ("✅" if d["status"] == "COMPLETED" else "❌")

    status_msg = (
        f"🔍 <b>ESCROW DEAL STATUS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🪪 <b>Deal ID:</b> {deal_id}\n"
        f"📌 <b>Status:</b> {badge} {d['status']}\n"
        f"💰 <b>Amount:</b> ₹{d['amount']:,.0f}\n"
        f"👤 <b>Seller:</b> {d['seller']}\n"
        f"👤 <b>Buyer:</b> {d['buyer']}\n"
        f"⚡ <b>Escrower:</b> {d['escrower']}"
    )
    await update.message.reply_text(status_msg, parse_mode="HTML")

# 8. Escrow Stats Command (/stats)
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats_msg = (
        f"📈 <b>@CHIKUESCROWSERVICE OFFICIAL STATS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🤝 <b>Total Deals Completed:</b> {STATS['total_deals']}\n"
        f"💼 <b>Total Volume Processed:</b> ₹{STATS['total_volume']:,.2f}\n"
        f"💵 <b>Total Escrow Fees:</b> ₹{STATS['total_fees']:,.2f}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🛡️ <i>100% Safe & Trusted Deals with Chiku Escrow</i>"
    )
    await update.message.reply_text(stats_msg, parse_mode="HTML")

# 9. Fake Admin Impersonator Warning & Text Triggers
async def handle_text_and_security(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user = update.effective_user
    chat = update.effective_chat
    text = update.message.text.strip().lower()

    # Text Triggers (bina slash ke)
    if text in ["form", ".form"]:
        await form(update, context)
        return
    elif text in ["fees", "fee", ".fee", ".fees"]:
        await fee_command(update, context)
        return
    elif text in ["close", ".close"]:
        await close_deal(update, context)
        return

    # Fake Admin Detection
    if chat.type in ["group", "supergroup"]:
        # Agar user real admin nahi hai
        if not await is_admin(update, context):
            user_full_name = (user.first_name or "") + " " + (user.last_name or "")
            scam_keywords = ["chikunxt", "harshal", "chiku escrow", "admin", "official escrow", "escrow service"]
            
            is_suspicious = any(kw in user_full_name.lower() for kw in scam_keywords)
            if user.username:
                is_suspicious = is_suspicious or any(kw in user.username.lower() for kw in ["chikunxt", "harshalnxt", "chikuadmin"])

            if is_suspicious:
                warning_text = (
                    f"🚨 <b>FAKE ADMIN / SCAM ALERT!</b> 🚨\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"⚠️ Member {user.mention_html()} (<code>{user.id}</code>) admin ka naam/impersonate karne ki koshish kar raha hai!\n"
  

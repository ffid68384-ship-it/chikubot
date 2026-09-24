import os
import re
import random
import unicodedata
import threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Bot is running!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host='0.0.0.0', port=port)

BOT_TOKEN = "8938665546:AAGvZElRJ36ji3LP7qyG4W90vC2ZFIQRKJY"
OWNER_ID = 7364435907

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

# Normalize unicode text
def normalize_text(text: str) -> str:
    text = unicodedata.normalize('NFKD', text)
    small_caps = {
        'ꜱ': 's', 'ᴇ': 'e', 'ʟ': 'l', 'ʀ': 'r', 'ʙ': 'b', 'ᴜ': 'u',
        'ʏ': 'y', 'ᴅ': 'd', 'ᴀ': 'a', 'ᴛ': 't', 'ɪ': 'i', 'ᴏ': 'o', 'ᴡ': 'w'
    }
    for k, v in small_caps.items():
        text = text.replace(k, v).replace(k.upper(), v)
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
    cleaned = val_str.lower().replace("₹", "").replace(",", "").replace("rs", "").strip()
    match = re.search(r"(\d+(\.\d+)?)(\s*k)?", cleaned)
    if not match:
        return 0.0
    num = float(match.group(1))
    if match.group(3):
        num *= 1000
    return num

# Robust Field Extractor from Form text
def extract_fields(text: str):
    norm = normalize_text(text)
    fields = {"seller": "", "buyer": "", "details": "", "amount": "", "till": "SECURE"}
    for line in norm.splitlines():
        clean_l = re.sub(r'^[•\-\*\s]+', '', line).strip()
        m = re.match(r"^(seller|buyer|deal\s*details|deal\s*deatails|details|deal\s*amount|amount|escrow\s*till|till)\s*[:\-]\s*(.*)$", clean_l, re.IGNORECASE)
        if m:
            key = m.group(1).lower().replace(" ", "")
            val = m.group(2).strip()
            # Khali bullet ya doosra field aane par ignore
            val = re.sub(r'^[•\-\*]\s*[A-Z\s]+:.*$', '', val).strip()
            if "seller" in key:
                fields["seller"] = val
            elif "buyer" in key:
                fields["buyer"] = val
            elif "detail" in key:
                fields["details"] = val
            elif "amount" in key:
                fields["amount"] = val
            elif "till" in key and val:
                fields["till"] = val
    return fields

# Helper to format User with their Numeric ID
async def resolve_user_id(user_str: str, replied_msg, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    if not user_str or user_str == "N/A":
        return "N/A"
    if re.search(r"\(\d+\)", user_str):
        return user_str

    clean_user = user_str.strip().replace("@", "")

    # 1. Message Entities (Direct mention)
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
                        member = await context.bot.get_chat_member(chat_id, f"@{mention_text}")
                        if member and member.user:
                            return f"@{mention_text} ({member.user.id})"
                    except Exception:
                        pass

    # 2. Try fetching from group
    try:
        member = await context.bot.get_chat_member(chat_id, f"@{clean_user}")
        if member and member.user:
            return f"@{clean_user} ({member.user.id})"
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
        await update.message.reply_text("❌ Kripya sahi amount likhein (e.g. <code>/fee 1500</code> ya <code>/fee 29k</code>)!", parse_mode="HTML")
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

# 3. Form Reply par ESCROW DEAL generate karke Pin karna (/deal)
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
    if amount_num > 0:
        _, _, fee_display, _ = get_fee_breakdown(amount_num)
        fee_line = f"\n\nFees {fee_display}"
    else:
        fee_line = ""

    deal_id = f"DL-CHIKU-{random.randint(1000, 9999)}"
    escrower_user = update.effective_user
    escrower_mention = escrower_user.mention_html()
    escrower_id = escrower_user.id

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
        await context.bot.pin_chat_message(
            chat_id=update.effective_chat.id,
            message_id=sent_msg.message_id
        )
    except Exception as e:
        print(f"Pin error: {e}")

# 4. Short-Cut /close Command (Auto-detect from replied slip or manual)
async def close_deal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ Sirf escrow admin yeh command chala sakta hai.")
        return

    amount_str = ""
    buyer = ""
    seller = ""

    # Short-Cut logic: Check replied message
    replied_msg = update.message.reply_to_message
    if replied_msg and (replied_msg.text or replied_msg.caption):
        text = replied_msg.text or replied_msg.caption
        fields = extract_fields(text)
        
        # Extract buyer & seller handles
        if fields["buyer"]:
            buyer = fields["buyer"].split()[0]
        if fields["seller"]:
            seller = fields["seller"].split()[0]
        if fields["amount"]:
            amount_str = fields["amount"]

    # Manual args override if provided
    if len(context.args) >= 1 and not amount_str:
        amount_str = context.args[0]
    if len(context.args) >= 2 and not buyer:
        buyer = context.args[1]
    if len(context.args) >= 3 and not seller:
        seller = context.args[2]

    # Validate extracted data
    amount_num = parse_amount(amount_str)
    if amount_num <= 0 or not buyer or not seller:
        await update.message.reply_text(
            "⚠️ <b>Short-cut:</b> Deal slip ka <b>Reply</b> karke <code>/close</code> likhein.\n"
            "Ya manual likhein: <code>/close &lt;amount&gt; &lt;buyer&gt; &lt;seller&gt;</code>",
            parse_mode="HTML"
        )
        return

    amount_formatted = f"{amount_num:,.2f}"
    
    escrower_user = update.effective_user
    if escrower_user.username:
        escrower_tag = f"@{escrower_user.username}"
    else:
        escrower_tag = escrower_user.mention_html()

    trade_id = f"DL-CHIKU-{random.randint(1000, 9999)}"

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
        await context.bot.pin_chat_message(
            chat_id=update.effective_chat.id,
            message_id=sent_msg.message_id
        )
    except Exception as e:
        print(f"Pin error: {e}")

if __name__ == '__main__':
    threading.Thread(target=run_web, daemon=True).start()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("form", form))
    app.add_handler(CommandHandler("fee", fee_command))
    app.add_handler(CommandHandler("fees", fee_command))
    app.add_handler(CommandHandler("deal", start_deal))
    app.add_handler(CommandHandler("close", close_deal))
    
    print("Bot chalu ho gaya hai...")
    app.run_polling()

import os
import re
import random
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

# Aapka Naya Bot Token
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

# Fee Calculation Helper
def get_fee_breakdown(amount: float):
    # Slab Rules:
    # 1 se 190 -> 10
    # 191 se 599 -> 20
    # 600 se 2000 -> 3.5%
    # 2001 se 3000 -> 3%
    # > 3000 -> 3%
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

# Parse Amount string (e.g. 29k -> 29000, 500 -> 500)
def parse_amount(val_str: str) -> float:
    cleaned = val_str.lower().replace("₹", "").replace(",", "").strip()
    match = re.search(r"(\d+(\.\d+)?)(\s*k)?", cleaned)
    if not match:
        return 0.0
    num = float(match.group(1))
    if match.group(3):
        num *= 1000
    return num

# 1. Blank Form + Fee Structure Command (/form)
async def form(update: Update, context: ContextTypes.DEFAULT_TYPE):
    form_text = (
        "<b>ESCROW DEAL FORM</b>\n\n"
        "• <b>SELLER :</b> \n"
        "• <b>BUYER :</b> \n"
        "• <b>DEAL DETAILS :</b> \n"
        "• <b>DEAL AMOUNT :</b> \n"
        "• <b>ESCROW TILL :</b> SECURE\n"
        "• <b>FOR RELEASE SELLER UPI :</b> \n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "<b>@CHIKUESCROWSERVICE CHARGES -</b>\n\n"
        "• Under ₹190 - ₹10\n"
        "• ₹191 To ₹599 - ₹20\n"
        "• ₹600 To ₹2000 - 3.5%\n"
        "• ₹2001 To ₹3000 - 3%\n"
        "• Upper Than ₹3000 - 3%\n\n"
        "📱 <b>RG :</b> @CHIKUNXT\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "<i>FOR MORE PROOFS CHECK GROUP PIN MESSAGES..</i>\n\n"
        "⚠️ <b>ESCROW FEES IS NON-REFUNDABLE NO MATTER IF THE DEAL GETS CANCELLED</b> ⚠️"
    )
    await update.message.reply_text(form_text, parse_mode="HTML")

# 2. Automatic Fee Calculator Command (/fee <amount>)
async def calculate_fee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "⚠️ Kripya amount likhein!\nExample: <code>/fee 2000</code>",
            parse_mode="HTML"
        )
        return

    amount = parse_amount(context.args[0])
    if amount <= 0:
        await update.message.reply_text("❌ Kripya sahi number amount daalein (e.g. <code>/fee 1500</code> ya <code>/fee 29k</code>)!", parse_mode="HTML")
        return

    fee, fee_rate, fee_display, seller_receives = get_fee_breakdown(amount)

    fee_text = (
        f"📊 <b>@CHIKUESCROWSERVICE FEE CALCULATOR</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Deal Amount:</b> ₹{amount:,.0f}\n"
        f"⚡ <b>Fee Rate:</b> {fee_rate}\n"
        f"💵 <b>Escrow Fee:</b> ₹{fee:,.0f}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"✅ <b>Seller Receives:</b> ₹{seller_receives:,.0f}\n\n"
        f"📱 <b>RG :</b> @CHIKUNXT"
    )
    await update.message.reply_text(fee_text, parse_mode="HTML")

# 3. Form Reply par Transaction Slip Generate karna (/deal)
async def start_deal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ Sirf escrow admin yeh command chala sakta hai.")
        return

    replied_msg = update.message.reply_to_message
    if not replied_msg or not replied_msg.text:
        await update.message.reply_text(
            "⚠️ Kripya bhare hue <b>ESCROW FORM</b> ka <b>Reply</b> karke <code>/deal</code> likhein!",
            parse_mode="HTML"
        )
        return

    text = replied_msg.text

    def extract_val(pattern):
        match = re.search(pattern, text, re.IGNORECASE)
        return match.group(1).strip() if match else "N/A"

    seller_raw = extract_val(r"SELLER\s*:\s*(.+)")
    buyer_raw = extract_val(r"BUYER\s*:\s*(.+)")
    details = extract_val(r"DEAL\s*DEATAILS\s*:\s*(.+)|DEAL\s*DETAILS\s*:\s*(.+)")
    amount_raw = extract_val(r"DEAL\s*AMOUNT\s*:\s*(.+)")
    escrow_till = extract_val(r"ESCROW\s*TILL\s*:\s*(.+)")

    # Agar form mein Telegram entities/mentions hain toh user ID extract karna
    def format_user_with_id(user_str):
        # Agar user_str me already bracket me id hai to waisi hi rakhna
        if "(" in user_str and ")" in user_str:
            return user_str
        
        # Message entities se match karna
        clean_user = user_str.strip().lstrip("@")
        if replied_msg.entities:
            for entity in replied_msg.entities:
                if entity.type == "text_mention" and entity.user:
                    if entity.user.username and entity.user.username.lower() == clean_user.lower():
                        return f"@{entity.user.username} ({entity.user.id})"
                    elif entity.user.first_name and clean_user.lower() in entity.user.first_name.lower():
                        return f"{entity.user.mention_html()} ({entity.user.id})"
        return user_str

    seller_formatted = format_user_with_id(seller_raw)
    buyer_formatted = format_user_with_id(buyer_raw)

    # Fee calculate karna
    amount_num = parse_amount(amount_raw)
    if amount_num > 0:
        _, _, fee_display, _ = get_fee_breakdown(amount_num)
        fee_line = f"\nFees {fee_display}"
    else:
        fee_line = ""

    deal_id = f"DL-CHIKU-{random.randint(1000, 9999)}"
    escrower_user = update.effective_user
    escrower_mention = escrower_user.mention_html()
    escrower_id = escrower_user.id

    # Aapka exact format
    formatted_slip = (
        f"<b>TRANSACTION</b>\n"
        f"🪪 <b>DEAL ID:</b> {deal_id}\n\n"
        f"• <b>ꜱᴇʟʟᴇʀ :</b> {seller_formatted}\n\n"
        f"• <b>ʙᴜʏᴇʀ  :</b> {buyer_formatted}\n\n"
        f"• <b>ᴅᴇᴀʟ ᴅᴇᴀᴛᴀɪʟꜱ :</b> {details}\n\n"
        f"• <b>ᴅᴇᴀʟ ᴀᴍᴏᴜɴᴛ :</b> {amount_raw}\n\n"
        f"• <b>ᴇꜱᴄʀᴏᴡ ᴛɪʟʟ :</b> {escrow_till}\n\n"
        f"<b>Escrower :</b> {escrower_mention} ({escrower_id})\n"
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

# 4. Final Deal Complete Receipt (/close <amount> <buyer> <seller>)
async def close_deal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ Sirf escrow admin yeh command chala sakta hai.")
        return

    if len(context.args) < 3:
        await update.message.reply_text(
            "Format galat hai!\nAise likhein:\n`/close <amount> <buyer> <seller>`", 
            parse_mode="Markdown"
        )
        return

    amount = context.args[0]
    buyer = context.args[1]
    seller = context.args[2]
    escrow_by = update.effective_user.mention_html()
    trade_id = f"DL-CHIKU-{random.randint(1000, 9999)}"

    message_text = (
        f"<b>TRANSACTION !!</b>\n"
        f"✅ <b>Deal Completed</b>\n"
        f"🪪 <b>Trade ID:</b> {trade_id}\n"
        f"📤 <b>Released:</b> ₹{amount}\n"
        f"👤 <b>Escrowed By:</b> {escrow_by}\n\n"
        f"~ {buyer} and {seller} are requested to drop the vouch before leaving 👇\n\n"
        f"<code>Vouch @CHIKUxTRANSACTIONBOT for ₹{amount} smooth escrow deal</code>"
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
    app.add_handler(CommandHandler("fee", calculate_fee))
    app.add_handler(CommandHandler("deal", start_deal))
    app.add_handler(CommandHandler("close", close_deal))
    
    print("Bot chalu ho gaya hai...")
    app.run_polling()
    

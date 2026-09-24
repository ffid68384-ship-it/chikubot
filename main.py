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

BOT_TOKEN = "8938665546:AAHsgsMsFQlu7sucO4qCHIoxC5P25MAuQFc"
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
    # 1 to 190 -> Rs 10
    # 191 to 599 -> Rs 20
    # 600 to 2000 -> 3.5%
    # 2001 to 3000 -> 3%
    # > 3000 -> 3%
    if amount <= 190:
        fee = 10.0
        rate = "Flat ₹10"
    elif amount <= 599:
        fee = 20.0
        rate = "Flat ₹20"
    elif amount <= 2000:
        fee = round((amount * 0.035), 2)
        rate = "3.5%"
    else:
        fee = round((amount * 0.03), 2)
        rate = "3%"
    seller_receives = amount - fee
    return fee, rate, seller_receives

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

    try:
        raw_val = context.args[0].lower().replace("k", "000").replace("₹", "").replace(",", "")
        amount = float(raw_val)
    except ValueError:
        await update.message.reply_text("❌ Kripya sahi number amount daalein (e.g. <code>/fee 1500</code>)!", parse_mode="HTML")
        return

    if amount <= 0:
        await update.message.reply_text("❌ Amount 0 se zyada hona chahiye.")
        return

    fee, fee_rate, seller_receives = get_fee_breakdown(amount)

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

# 3. Deal Active Verification via Form Reply (/deal)
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

    seller = extract_val(r"SELLER\s*:\s*(.+)")
    buyer = extract_val(r"BUYER\s*:\s*(.+)")
    details = extract_val(r"DEAL\s*DEATAILS\s*:\s*(.+)|DEAL\s*DETAILS\s*:\s*(.+)")
    amount_str = extract_val(r"DEAL\s*AMOUNT\s*:\s*(.+)")
    escrow_till = extract_val(r"ESCROW\s*TILL\s*:\s*(.+)")

    # Amount se automatically number nikal kar fee calculate karna
    clean_num = re.sub(r"[^\d.]", "", amount_str.lower().replace("k", "000"))
    fee_section = ""
    try:
        if clean_num:
            amount_val = float(clean_num)
            fee, rate, payout = get_fee_breakdown(amount_val)
            fee_section = (
                f"• <b>ᴇꜱᴄʀᴏᴡ ꜰᴇᴇ :</b> ₹{fee:,.0f} ({rate})\n"
                f"• <b>ꜱᴇʟʟᴇʀ ᴘᴀʏᴏᴜᴛ :</b> ₹{payout:,.0f}\n"
            )
    except Exception:
        fee_section = ""

    deal_id = f"DL-CHIKU-{random.randint(1000, 9999)}"
    escrower_user = update.effective_user
    escrower_name = escrower_user.mention_html()
    escrower_id = escrower_user.id

    formatted_slip = (
        f"<b>TRANSACTION</b>\n"
        f"🪪 <b>DEAL ID:</b> {deal_id}\n\n"
        f"• <b>ꜱᴇʟʟᴇʀ :</b> {seller}\n"
        f"• <b>ʙᴜʏᴇʀ :</b> {buyer}\n"
        f"• <b>ᴅᴇᴀʟ ᴅᴇᴀᴛᴀɪʟꜱ :</b> {details}\n"
        f"• <b>ᴅᴇᴀʟ ᴀᴍᴏᴜɴᴛ :</b> {amount_str}\n"
        f"{fee_section}"
        f"• <b>ᴇꜱᴄʀᴏᴡ ᴛɪʟʟ :</b> {escrow_till}\n\n"
        f"<b>Escrower :</b> {escrower_name} (<code>{escrower_id}</code>)\n\n"
        f"⚠️ <b>ESCROW FEES IS NON - REFUNDABLE NO MATTER IF THE DEAL GETS CANCELLED</b> ⚠️"
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
    

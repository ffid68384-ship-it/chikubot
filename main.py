import os
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

# Deal start form command
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

# Deal complete receipt command
async def deal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user_id = update.effective_user.id

    # Check karein agar user group admin hai ya bot owner hai
    try:
        admins = await context.bot.get_chat_administrators(chat.id)
        admin_ids = [admin.user.id for admin in admins]
    except Exception:
        admin_ids = []

    if (user_id not in admin_ids) and (user_id != OWNER_ID):
        await update.message.reply_text("❌ Sirf escrow admin yeh command chala sakta hai.")
        return

    if len(context.args) < 3:
        await update.message.reply_text(
            "Format galat hai!\nAise likhein:\n`/deal <amount> <buyer> <seller>`", 
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
        chat_id=chat.id,
        text=message_text,
        parse_mode="HTML"
    )

    try:
        await context.bot.pin_chat_message(
            chat_id=chat.id,
            message_id=sent_msg.message_id
        )
    except Exception as e:
        print(f"Pin error: {e}")

if __name__ == '__main__':
    threading.Thread(target=run_web, daemon=True).start()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("form", form))
    app.add_handler(CommandHandler("deal", deal))
    
    print("Bot chalu ho gaya hai...")
    app.run_polling()
    

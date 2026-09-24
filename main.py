import random
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

BOT_TOKEN = "8938665546:AAHsgsMsFQlu7sucO4qCHIoxC5P25MAuQFc"
ADMIN_IDS = [7364435907] 

async def deal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
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
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("deal", deal))
    print("Bot chalu ho gaya hai...")
    app.run_polling()
  

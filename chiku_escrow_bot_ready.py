import os
import re
import threading
import unicodedata
import logging
from html import escape

from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ============================================================
# CHIKU ESCROW BOT
# Clean version:
# - No force-join
# - No promotional channel
# - No A-TOOLS / external channel links
# - Bot token is read securely from BOT_TOKEN environment variable
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# -------------------- WEB KEEP-ALIVE -------------------------

web_app = Flask(__name__)


@web_app.route("/")
def home():
    return "Chiku Escrow Active 24/7"


def run_web():
    port = int(os.environ.get("PORT", "10000"))
    web_app.run(host="0.0.0.0", port=port)


# -------------------- CONFIG -------------------------

# IMPORTANT:
# Set BOT_TOKEN in your hosting environment.
# DO NOT paste the token directly into this file.
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN environment variable is missing. "
        "Add your new Telegram bot token as BOT_TOKEN in your hosting settings."
    )

OWNER_ID = 7364435907

# -------------------- IN-MEMORY DATA -------------------------

DEALS_DB = {}
STATS = {
    "deals": 0,
    "vol": 0.0,
    "fees": 0.0,
}

DEAL_CTR = 11254
CURR_DEAL = None
LAST_PIN = None


# -------------------- ADMIN CHECK -------------------------

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    chat = update.effective_chat

    if not user or not chat:
        return False

    if user.id == OWNER_ID or chat.type == "private":
        return True

    try:
        admins = await context.bot.get_chat_administrators(chat.id)
        return any(admin.user.id == user.id for admin in admins)
    except Exception:
        # If Telegram temporarily fails to return admin information,
        # do not block the command.
        return True


# -------------------- TEXT NORMALIZATION -------------------------

MAP = {
    "ɢ": "g", "ɪ": "i", "ɴ": "n", "ʀ": "r", "ʏ": "y",
    "ʙ": "b", "ʜ": "h", "ʟ": "l", "ꜱ": "s", "ғ": "f",
    "ᴀ": "a", "ᴄ": "c", "ᴅ": "d", "ᴇ": "e", "ᴋ": "k",
    "ᴍ": "m", "ᴏ": "o", "ᴘ": "p", "ᴛ": "t", "ᴜ": "u",
    "ᴡ": "w", "ᴊ": "j", "ǫ": "q", "ᴠ": "v", "ᴢ": "z",
    "𝖴": "u", "U": "u", "O": "o",
    "О": "o", "а": "a", "е": "e", "о": "o", "р": "p",
    "с": "c", "у": "y", "х": "x", "м": "m", "н": "n",
    "т": "t",
}


def clean_txt(text):
    if not text:
        return ""

    normalized = unicodedata.normalize("NFKD", str(text))
    return "".join(MAP.get(ch, ch) for ch in normalized).lower()


# -------------------- FEE CALCULATOR -------------------------

def calc_fee(amount):
    if amount <= 0:
        return 0.0, "0%", "0₹", 0.0

    if amount <= 190:
        fee = 10.0
        return fee, "Flat ₹10", "Rs 10", amount - fee

    if amount <= 599:
        fee = 20.0
        return fee, "Flat ₹20", "Rs 20", amount - fee

    if amount <= 2000:
        fee = round(amount * 0.035, 2)
        return fee, "3.5%", f"3.5% - {round(fee)}₹", amount - fee

    fee = round(amount * 0.03, 2)
    return fee, "3%", f"3% - {round(fee)}₹", amount - fee


# -------------------- FORM PARSER -------------------------

def parse_form(raw):
    data = {
        "seller": "",
        "buyer": "",
        "details": "",
        "amount": 0.0,
        "till": "",
        "id": "",
    }

    if not raw:
        return data

    clean_full = clean_txt(raw)

    deal_id = re.search(r"dl[-_ ]*chiku[-_ ]*(\d+)", clean_full, re.I)
    if deal_id:
        data["id"] = f"DL-CHIKU-{deal_id.group(1)}"

    raw_lines = raw.splitlines()
    clean_lines = clean_full.splitlines()

    for index, (raw_line, clean_line) in enumerate(
        zip(raw_lines, clean_lines)
    ):
        if not clean_line.strip():
            continue

        if ":" in raw_line:
            value = raw_line.split(":", 1)[1].strip()
        elif "-" in raw_line:
            value = raw_line.split("-", 1)[1].strip()
        else:
            value = ""

        if ":" in clean_line:
            label = clean_line.split(":", 1)[0]
        elif "-" in clean_line:
            label = clean_line.split("-", 1)[0]
        else:
            label = clean_line

        label = re.sub(r"^[•*\-\s]+", "", label).strip()

        if (label in ("seller", "s") or label.endswith(" seller")) and not data["seller"]:
            data["seller"] = value

        elif (label in ("buyer", "b") or label.endswith(" buyer")) and not data["buyer"]:
            data["buyer"] = value

        elif any(word in label for word in ("detail", "deatail")) and not data["details"]:
            data["details"] = value

            if index + 1 < len(raw_lines):
                next_clean = clean_lines[index + 1].strip()

                if next_clean and not any(
                    word in next_clean
                    for word in (
                        "•", "*", "-", ":", "amount", "amt",
                        "till", "escrow", "seller", "buyer"
                    )
                ):
                    data["details"] += " " + raw_lines[index + 1].strip()

        elif any(word in label for word in ("amount", "amt", "price", "cost")):
            if data["amount"] == 0.0:
                match = re.search(
                    r"(\d+(?:\.\d+)?)",
                    clean_txt(value).replace(",", ""),
                )
                if match:
                    data["amount"] = float(match.group(1))

        elif "till" in label and not data["till"]:
            data["till"] = value

    # Fallback amount detection
    if data["amount"] == 0.0:
        no_usernames = re.sub(r"@\w+", "", clean_full).replace(",", "")

        match = re.search(
            r"(?:amount|amt|price)[\s:\-]*[₹rs\s]*(\d+(?:\.\d+)?)",
            no_usernames,
        )

        if match:
            data["amount"] = float(match.group(1))
        else:
            match = re.search(
                r"[₹rs]\s*(\d+(?:\.\d+)?)",
                no_usernames,
            )
            if match:
                data["amount"] = float(match.group(1))

    return data


# -------------------- USER RESOLUTION -------------------------

async def resolve_user(value, replied_message, context, chat_id):
    if not value or value.upper() == "N/A":
        return value or "N/A"

    clean = value.strip()

    if "(" in clean and ")" in clean:
        return clean

    if clean.isdigit():
        user_id = int(clean)
        return f'<a href="tg://user?id={user_id}">{user_id}</a> ({user_id})'

    if clean.lower() in ("me", "i", "myself", "mai"):
        if replied_message and replied_message.from_user:
            user = replied_message.from_user
            if user.username:
                return f"@{escape(user.username)} ({user.id})"
            return f"{escape(user.first_name)} ({user.id})"

    if replied_message and replied_message.entities:
        for entity in replied_message.entities:
            if entity.type == "text_mention" and entity.user:
                return f"{entity.user.mention_html()} ({entity.user.id})"

    if clean.startswith("@"):
        try:
            member = await context.bot.get_chat_member(chat_id, clean)
            if member and member.user:
                return f"{escape(clean)} ({member.user.id})"
        except Exception:
            pass

    return escape(clean)


# -------------------- HELPERS -------------------------

async def delete_command(update: Update):
    try:
        if update.message:
            await update.message.delete()
    except Exception:
        pass


async def send_fee_calculator(update: Update, amount: float):
    fee, rate, _, received = calc_fee(amount)

    await update.message.reply_text(
        "📊 <b>@CHIKUESCROWSERVICE FEE CALCULATOR</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Deal Amount:</b> ₹{amount:,.0f}\n"
        f"⚡ <b>Fee Rate:</b> {rate}\n"
        f"💵 <b>Escrow Fee:</b> ₹{fee:,.0f}\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"✅ <b>Seller Receives:</b> ₹{received:,.0f}\n\n"
        "📱 <b>RG :</b> @CHIKUNXT",
        parse_mode="HTML",
    )


# -------------------- COMMANDS -------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ <b>Chiku Escrow Bot is active.</b>\n\n"
        "Use <code>Form</code> for a deal form or "
        "<code>Fees 2000</code> to calculate fees.",
        parse_mode="HTML",
    )


async def cmd_form(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = (
        "<b>ᴇꜱᴄʀᴏᴡ ᴅᴇᴀʟ ғᴏʀᴍ</b>\n\n"
        "• <b>ꜱᴇʟʟᴇʀ :</b> \n\n"
        "• <b>ʙᴜʏᴇʀ :</b> \n\n"
        "• <b>ᴅᴇᴀʟ ᴅᴇᴀᴛᴀɪʟꜱ :</b> \n\n"
        "• <b>ᴅᴇᴀʟ ᴀᴍᴏᴜɴᴛ :</b> \n\n"
        "• <b>ᴇꜱᴄʀᴏᴡ ᴛɪʟʟ :</b> \n\n"
        "• <b>ғᴏʀ ʀᴇʟᴇᴀsᴇ sᴇʟʟᴇʀ ᴜᴘɪ :</b> \n\n"
        "<i>ғᴏʀ ᴍᴏʀᴇ ᴘʀᴏᴏғs ᴄʜᴇᴄᴋ ɢʀᴏᴜᴘ ᴘɪɴ ᴍᴇssᴀɢᴇs..</i>\n\n"
        "⚠️ <b>ESCROW FEES IS NON - REFUNDABLE NO MATTER IF THE DEAL GETS CANCELLED</b> ⚠️"
    )

    await update.message.reply_text(message, parse_mode="HTML")


async def cmd_fee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "<b>@CHIKUESCROWSERVICE CHARGES -</b>\n\n"
            "• Under ₹190 - ₹10\n"
            "• ₹191 To ₹599 - ₹20\n"
            "• ₹600 To ₹2000 - 3.5%\n"
            "• ₹2001 To ₹3000 - 3%\n"
            "• Upper Than ₹3000 - 3%\n\n"
            "📱 <b>RG :</b> @CHIKUNXT\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "💡 Check: <code>fees 2000</code>",
            parse_mode="HTML",
        )
        return

    number = re.sub(r"[^\d.]", "", context.args[0])

    try:
        amount = float(number)
    except ValueError:
        return

    if amount > 0:
        await send_fee_calculator(update, amount)


async def cmd_deal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global DEAL_CTR, CURR_DEAL, LAST_PIN

    if not await is_admin(update, context):
        return

    replied = update.message.reply_to_message

    if not replied or not (replied.text or replied.caption):
        await update.message.reply_text(
            "⚠️ Bhare hue <b>FORM</b> ka reply karke "
            "<code>/deal</code> bhejo!",
            parse_mode="HTML",
        )
        return

    if LAST_PIN:
        try:
            await context.bot.unpin_chat_message(
                chat_id=update.effective_chat.id,
                message_id=LAST_PIN,
            )
        except Exception:
            pass

    form = parse_form(replied.text or replied.caption)

    if context.args:
        number = re.sub(r"[^\d.]", "", context.args[0])
        try:
            if number:
                form["amount"] = float(number)
        except ValueError:
            pass

    seller = await resolve_user(
        form["seller"] or "N/A",
        replied,
        context,
        update.effective_chat.id,
    )

    buyer = await resolve_user(
        form["buyer"] or "N/A",
        replied,
        context,
        update.effective_chat.id,
    )

    amount = form["amount"]
    _, _, fee_tag, _ = calc_fee(amount)
    fee_line = f"\n\nFees {fee_tag}" if amount > 0 else ""

    deal_id = f"DL-CHIKU-{DEAL_CTR}"
    DEAL_CTR += 1
    CURR_DEAL = deal_id

    user = update.effective_user

    amount_label = f"₹{amount:,.0f}" if amount > 0 else "Deal Amount"
    details = form["details"] or "N/A"
    till = form["till"] or "SECURE"

    message = (
        "<b>ESCROW DEAL</b>\n"
        f"🪪 <b>DEAL ID:</b> {deal_id}\n\n"
        f"• <b>ꜱᴇʟʟᴇʀ :</b> {seller}\n"
        f"• <b>ʙᴜʏᴇʀ  :</b> {buyer}\n\n"
        f"• <b>ᴅᴇᴀʟ ᴅᴇᴀᴛᴀɪʟꜱ :</b> {escape(details)}\n"
        f"• <b>ᴅᴇᴀʟ ᴀᴍᴏᴜɴᴛ :</b> {amount_label}\n"
        f"• <b>ᴇꜱᴄʀᴏᴡ ᴛɪʟʟ :</b> {escape(till)}\n\n"
        f"<b>Escrower :</b> {user.mention_html()} ({user.id})"
        f"{fee_line}"
    )

    sent = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message,
        parse_mode="HTML",
    )

    try:
        await context.bot.pin_chat_message(
            chat_id=update.effective_chat.id,
            message_id=sent.message_id,
            disable_notification=True,
        )
        LAST_PIN = sent.message_id
    except Exception:
        pass

    DEALS_DB[deal_id] = {
        "status": "ACTIVE",
        "seller": seller,
        "buyer": buyer,
        "amount": amount,
        "escrower": (
            f"@{user.username}"
            if user.username
            else user.first_name
        ),
        "details": details,
        "msg_id": sent.message_id,
    }


async def cmd_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    chat_id = update.effective_chat.id
    replied = update.message.reply_to_message

    deal_id = None
    amount = 0.0
    seller = ""
    buyer = ""

    if replied and (replied.text or replied.caption):
        form = parse_form(replied.text or replied.caption)
        deal_id = form["id"]

        if deal_id in DEALS_DB:
            deal = DEALS_DB[deal_id]
        else:
            deal = {}

        amount = form["amount"] or deal.get("amount", 0.0)
        seller = form["seller"] or deal.get("seller", "")
        buyer = form["buyer"] or deal.get("buyer", "")

    if not deal_id and CURR_DEAL and CURR_DEAL in DEALS_DB:
        deal_id = CURR_DEAL
        deal = DEALS_DB[deal_id]
        amount = amount or deal["amount"]
        seller = seller or deal["seller"]
        buyer = buyer or deal["buyer"]

    deal_id = deal_id or CURR_DEAL or f"DL-CHIKU-{DEAL_CTR}"

    amount_label = f"₹{amount:,.0f}" if amount > 0 else "Deal Amount"
    seller_tag = seller.split()[0] if seller else "@Seller"
    buyer_tag = buyer.split()[0] if buyer else "@Buyer"

    message = (
        "💰 <b>PAYMENT RECEIVED & CONFIRMED!</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"🪪 <b>Deal ID:</b> {escape(deal_id)}\n"
        f"💵 <b>Amount:</b> {amount_label}\n"
        f"👤 <b>Buyer:</b> {buyer_tag}\n"
        f"👤 <b>Seller:</b> {seller_tag}\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        "🤝 <b>TRANSFER ACCESS TO BUYER WITH SCREENRECORDS !!</b> 🤝\n\n"
        "⚠️ <i>Seller video record karke access transfer karein "
        "aur Buyer verify karke vouch karein.</i>"
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text=message,
        parse_mode="HTML",
    )


async def cmd_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CURR_DEAL, LAST_PIN

    await delete_command(update)

    if not await is_admin(update, context):
        return

    chat_id = update.effective_chat.id
    replied = update.message.reply_to_message

    deal_id = None
    amount = 0.0
    seller = ""
    buyer = ""
    replied_message_id = None

    if replied and (replied.text or replied.caption):
        replied_message_id = replied.message_id
        form = parse_form(replied.text or replied.caption)

        deal_id = form["id"]
        amount = form["amount"]
        seller = form["seller"]
        buyer = form["buyer"]

        if deal_id in DEALS_DB:
            deal = DEALS_DB[deal_id]
            replied_message_id = deal.get("msg_id", replied_message_id)
            amount = amount or deal.get("amount", 0.0)
            seller = seller or deal.get("seller", "")
            buyer = buyer or deal.get("buyer", "")

    if not deal_id and CURR_DEAL and CURR_DEAL in DEALS_DB:
        deal_id = CURR_DEAL
        deal = DEALS_DB[deal_id]

        amount = amount or deal["amount"]
        seller = seller or deal["seller"]
        buyer = buyer or deal["buyer"]
        replied_message_id = deal.get("msg_id")

    if context.args:
        number = re.sub(r"[^\d.]", "", context.args[0])
        try:
            if number:
                amount = float(number)
        except ValueError:
            pass

    seller_tag = seller.split()[0] if seller else "@Seller"
    buyer_tag = buyer.split()[0] if buyer else "@Buyer"

    deal_id = deal_id or CURR_DEAL or f"DL-CHIKU-{DEAL_CTR}"
    user = update.effective_user

    STATS["deals"] += 1
    STATS["vol"] += amount
    STATS["fees"] += calc_fee(amount)[0]

    if deal_id in DEALS_DB:
        DEALS_DB[deal_id]["status"] = "COMPLETED"

    target = replied_message_id or LAST_PIN

    if target:
        try:
            await context.bot.unpin_chat_message(
                chat_id=chat_id,
                message_id=target,
            )
        except Exception:
            pass

    amount_label = f"₹{amount:,.2f}" if amount > 0 else "Deal Amount"
    escrowed_by = (
        f"@{escape(user.username)}"
        if user.username
        else user.mention_html()
    )

    message = (
        "✅ <b>Deal Completed</b>\n"
        "🪪 <b>Trade ID:</b>\n"
        f"{escape(deal_id)}\n"
        f"📤 <b>Released:</b> {amount_label}\n"
        "👤 <b>Escrowed By:</b>\n"
        f"{escrowed_by}\n\n"
        f"~ {buyer_tag} and {seller_tag}\n"
        "are requested to drop the\n"
        "vouch before leaving 👇🏻\n\n"
        f"<code>Vouch @chikuescrowservice for {amount_label} smooth escrow deal</code>"
    )

    sent = await context.bot.send_message(
        chat_id=chat_id,
        text=message,
        parse_mode="HTML",
    )

    try:
        await context.bot.pin_chat_message(
            chat_id=chat_id,
            message_id=sent.message_id,
            disable_notification=True,
        )
        LAST_PIN = sent.message_id
    except Exception:
        pass


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global LAST_PIN

    await delete_command(update)

    if not await is_admin(update, context):
        return

    deal_id = CURR_DEAL or f"DL-CHIKU-{DEAL_CTR}"

    if deal_id in DEALS_DB:
        DEALS_DB[deal_id]["status"] = "CANCELLED"

    if LAST_PIN:
        try:
            await context.bot.unpin_chat_message(
                chat_id=update.effective_chat.id,
                message_id=LAST_PIN,
            )
        except Exception:
            pass

    sent = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=(
            "❌ <b>DEAL CANCELLED</b>\n"
            f"🪪 <b>ID:</b> {escape(deal_id)}\n"
            f"👤 <b>By:</b> {update.effective_user.mention_html()}"
        ),
        parse_mode="HTML",
    )

    try:
        await context.bot.pin_chat_message(
            chat_id=update.effective_chat.id,
            message_id=sent.message_id,
            disable_notification=True,
        )
        LAST_PIN = sent.message_id
    except Exception:
        pass


async def cmd_refund(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global LAST_PIN

    await delete_command(update)

    if not await is_admin(update, context):
        return

    chat_id = update.effective_chat.id
    replied = update.message.reply_to_message

    deal_id = None
    amount = 0.0
    buyer = ""

    if replied and (replied.text or replied.caption):
        form = parse_form(replied.text or replied.caption)
        deal_id = form["id"]
        amount = form["amount"]
        buyer = form["buyer"]

        if deal_id in DEALS_DB:
            deal = DEALS_DB[deal_id]
            amount = amount or deal.get("amount", 0.0)
            buyer = buyer or deal.get("buyer", "")

    if not deal_id and CURR_DEAL and CURR_DEAL in DEALS_DB:
        deal_id = CURR_DEAL
        deal = DEALS_DB[deal_id]
        amount = amount or deal["amount"]
        buyer = buyer or deal["buyer"]

    if context.args:
        number = re.sub(r"[^\d.]", "", context.args[0])
        try:
            if number:
                amount = float(number)
        except ValueError:
            pass

    buyer_tag = buyer.split()[0] if buyer else "@Buyer"
    deal_id = deal_id or CURR_DEAL or f"DL-CHIKU-{DEAL_CTR}"

    if deal_id in DEALS_DB:
        DEALS_DB[deal_id]["status"] = "REFUNDED"

    if LAST_PIN:
        try:
            await context.bot.unpin_chat_message(
                chat_id=chat_id,
                message_id=LAST_PIN,
            )
        except Exception:
            pass

    amount_label = f"₹{amount:,.2f}" if amount > 0 else "Deal Amount"

    message = (
        "🔄 <b>DEAL REFUNDED</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"🪪 <b>Trade ID:</b> {escape(deal_id)}\n"
        f"💵 <b>Refunded Amount:</b> {amount_label}\n"
        f"👤 <b>Refunded To:</b> {buyer_tag}\n"
        f"👤 <b>Admin:</b> {update.effective_user.mention_html()}\n\n"
        "🔒 <i>Deal amount has been safely refunded back to buyer.</i>"
    )

    sent = await context.bot.send_message(
        chat_id=chat_id,
        text=message,
        parse_mode="HTML",
    )

    try:
        await context.bot.pin_chat_message(
            chat_id=chat_id,
            message_id=sent.message_id,
            disable_notification=True,
        )
        LAST_PIN = sent.message_id
    except Exception:
        pass


async def cmd_hold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global LAST_PIN

    await delete_command(update)

    if not await is_admin(update, context):
        return

    deal_id = CURR_DEAL or f"DL-CHIKU-{DEAL_CTR}"

    if deal_id in DEALS_DB:
        DEALS_DB[deal_id]["status"] = "ON HOLD"

    reason = (
        " ".join(context.args)
        if context.args
        else "Verification / Dispute Under Review"
    )

    if LAST_PIN:
        try:
            await context.bot.unpin_chat_message(
                chat_id=update.effective_chat.id,
                message_id=LAST_PIN,
            )
        except Exception:
            pass

    sent = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=(
            "⏳ <b>DEAL ON HOLD</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            f"🪪 <b>Deal ID:</b> {escape(deal_id)}\n"
            f"⚠️ <b>Reason:</b> {escape(reason)}\n"
            f"👤 <b>Action By:</b> {update.effective_user.mention_html()}\n\n"
            "🔒 <i>Release is paused.</i>"
        ),
        parse_mode="HTML",
    )

    try:
        await context.bot.pin_chat_message(
            chat_id=update.effective_chat.id,
            message_id=sent.message_id,
            disable_notification=True,
        )
        LAST_PIN = sent.message_id
    except Exception:
        pass


async def cmd_adminhold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    active_deals = {
        key: value
        for key, value in DEALS_DB.items()
        if value.get("status") in ("ACTIVE", "ON HOLD")
    }

    if not active_deals:
        await update.message.reply_text(
            "🛡️ <b>ADMIN HOLD STATUS</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "Abhi koi active hold deal nahi hai.",
            parse_mode="HTML",
        )
        return

    grouped = {}
    grand_total = 0.0

    for deal_id, info in active_deals.items():
        admin = info.get("escrower", "Unknown Escrower")
        grouped.setdefault(admin, []).append((deal_id, info))
        grand_total += info.get("amount", 0.0)

    output = [
        "🛡️ <b>ADMIN HOLD STATUS</b>",
        "━━━━━━━━━━━━━━━━━━━",
    ]

    for admin, deals in grouped.items():
        total_admin = sum(
            item[1].get("amount", 0.0)
            for item in deals
        )

        output.append(
            f"👤 <b>{escape(str(admin))}</b> — Hold: ₹{total_admin:,.2f}"
        )

        for deal_id, info in deals:
            amount = info.get("amount", 0.0)
            _, rate, _, net = calc_fee(amount)

            output.append(
                f"  • <b>{escape(deal_id)}</b> — "
                f"₹{amount:,.0f} ({escape(info.get('status', 'UNKNOWN'))})\n"
                f"    Fee: {rate} | Net: ₹{net:,.0f}"
            )

        output.append("")

    output.append("───────────────────")
    output.append(
        f"💰 <b>TOTAL HOLD ACROSS ALL ADMINS: ₹{grand_total:,.2f}</b>"
    )

    await update.message.reply_text(
        "\n".join(output),
        parse_mode="HTML",
    )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📈 <b>@CHIKUESCROWSERVICE STATS</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"🤝 <b>Total Deals:</b> {STATS['deals']}\n"
        f"💼 <b>Total Volume:</b> ₹{STATS['vol']:,.2f}\n"
        f"💵 <b>Total Fees:</b> ₹{STATS['fees']:,.2f}\n"
        "📱 <b>RG :</b> @CHIKUNXT",
        parse_mode="HTML",
    )


# -------------------- EDIT PROTECTION -------------------------

async def check_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    edited = update.edited_message

    if not edited or not edited.from_user:
        return

    if edited.from_user.id == OWNER_ID:
        return

    try:
        admins = await context.bot.get_chat_administrators(edited.chat_id)
        if any(admin.user.id == edited.from_user.id for admin in admins):
            return
    except Exception:
        pass

    try:
        await edited.delete()

        await context.bot.send_message(
            chat_id=edited.chat_id,
            text=(
                f"⚠️ {edited.from_user.mention_html()} "
                "<b>EDITED FORM/MESSAGE NOT ALLOWED ⚠️</b>"
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass


# -------------------- TEXT ROUTER -------------------------

async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    lower = text.lower()

    if lower in ("form", ".form"):
        await cmd_form(update, context)
        return

    if lower in ("fee", "fees", ".fee", ".fees"):
        await cmd_fee(update, context)
        return

    if lower in ("stats", ".stats"):
        await cmd_stats(update, context)
        return

    if lower in ("adminhold", ".adminhold"):
        await cmd_adminhold(update, context)
        return

    if lower in ("refund", ".refund"):
        await cmd_refund(update, context)
        return

    if lower in (
        "received", ".received",
        "recieved", ".recieved",
        "receive", ".receive",
        "recive", ".recive",
    ):
        await cmd_received(update, context)
        return

    match = re.match(
        r"^(?:fee|fees|\.fee|\.fees|/fee|/fees)\s+([^\s]+)",
        lower,
    )

    if match:
        number = re.sub(r"[^\d.]", "", match.group(1))

        try:
            amount = float(number)
        except ValueError:
            return

        if amount > 0:
            await send_fee_calculator(update, amount)


# -------------------- ERROR HANDLER -------------------------

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(
        "Unhandled exception while processing update",
        exc_info=context.error,
    )


# -------------------- MAIN -------------------------

def main():
    threading.Thread(
        target=run_web,
        daemon=True,
    ).start()

    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("form", cmd_form))
    application.add_handler(CommandHandler("fee", cmd_fee))
    application.add_handler(CommandHandler("fees", cmd_fee))
    application.add_handler(CommandHandler("deal", cmd_deal))

    for command in (
        "received",
        "recieved",
        "receive",
        "recive",
    ):
        application.add_handler(
            CommandHandler(command, cmd_received)
        )

    application.add_handler(CommandHandler("close", cmd_close))
    application.add_handler(CommandHandler("cancel", cmd_cancel))
    application.add_handler(CommandHandler("refund", cmd_refund))
    application.add_handler(CommandHandler("hold", cmd_hold))
    application.add_handler(CommandHandler("adminhold", cmd_adminhold))
    application.add_handler(CommandHandler("stats", cmd_stats))

    application.add_handler(
        MessageHandler(
            filters.UpdateType.EDITED_MESSAGE,
            check_edit,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_router,
        )
    )

    application.add_error_handler(error_handler)

    logger.info("Chiku Escrow Bot starting...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

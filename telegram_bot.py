# telegram_bot.py
import telegram
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
import requests
import os

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")  # Get token from env var
API_URL = os.environ.get("API_URL", "http://localhost:8099/api/check-cards")

def start(update, context):
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Hi! I'm your Card Pattern Analyzer Bot.\n\nSend me card numbers, one per line, and I'll analyze them for you.\n\n Use /upgrade to become premium and get unlimited access. \n\nTo view previous usages use /history"
    )

def check_card(update, context):
    card_numbers = update.message.text.splitlines()
    telegram_id = update.message.from_user.id

    try:
        payload = {"card_numbers": card_numbers, "telegram_id": telegram_id}
        response = requests.post(API_URL, json=payload)
        response.raise_for_status()
        data = response.json()

        message = ""
        for result in data["results"]:
            if "error" in result:
                message += f"Card Number: {result['card_number']}\n{result['error']}\n\n"
            else:
                message += f"Card Number: {result['card_number']}\n"
                message += f"  Is Valid: {result['is_valid']}\n"
                message += f"  Network: {result['network']}\n\n"

        context.bot.send_message(chat_id=update.effective_chat.id, text=message)
    except requests.exceptions.RequestException as e:
        context.bot.send_message(chat_id=update.effective_chat.id,
                                 text=f"An error occurred: {e}")


def upgrade(update, context):
    context.bot.send_message(chat_id=update.effective_chat.id, text="To upgrade to premium, please send $10 via PayPal to [PayPal email]. After paying use the /validate_payment command with transaction hash.")


def validate_payment(update, context):
    if not context.args:
        context.bot.send_message(chat_id=update.effective_chat.id, text="Please send payment hash after command. Ex. /validate_payment transaction_hash")
        return

    transaction_hash = " ".join(context.args)

    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, telegram_id FROM users WHERE telegram_id = ?", (update.message.from_user.id,))
    user = cursor.fetchone()
    if not user:
        conn.close()
        context.bot.send_message(chat_id=update.effective_chat.id, text="User Not found, Please Use /start command first")
        return

    user_id, telegram_id = user

    # Simulate payment validation with a simple hash checking
    if transaction_hash.startswith("valid_payment_"):
        cursor.execute("UPDATE users SET subscription_tier = 'premium' WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        context.bot.send_message(chat_id=update.effective_chat.id, text="You have successfully upgraded to premium!")
    else:
        conn.close()
        context.bot.send_message(chat_id=update.effective_chat.id, text="Payment not validated! Please be sure to send the correct transaction hash and use valid payment methods.")

def get_history(update, context):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, telegram_id FROM users WHERE telegram_id = ?", (update.message.from_user.id,))
    user = cursor.fetchone()
    if not user:
        conn.close()
        context.bot.send_message(chat_id=update.effective_chat.id, text="User Not found, Please Use /start command first")
        return

    user_id, telegram_id = user

    cursor.execute("SELECT card_number, check_time FROM usage_log WHERE user_id = ? ORDER BY check_time DESC LIMIT 10", (user_id,))
    usage_history = cursor.fetchall()
    conn.close()

    if not usage_history:
        context.bot.send_message(chat_id=update.effective_chat.id, text="No history found")
        return

    message = "Usage history for last 10 checks:\n\n"
    for card_number, check_time in usage_history:
        message += f"Card Number: {card_number}\n"
        message += f"Check Time: {check_time}\n\n"

    context.bot.send_message(chat_id=update.effective_chat.id, text=message)

def main():
    updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(MessageHandler(Filters.text & (~Filters.command), check_card))
    dispatcher.add_handler(CommandHandler("upgrade", upgrade))
    dispatcher.add_handler(CommandHandler("validate_payment", validate_payment, pass_args=True))
    dispatcher.add_handler(CommandHandler("history", get_history))
    
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
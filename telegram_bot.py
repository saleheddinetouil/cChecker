# telegram_bot.py
import logging
import os
import requests
from urllib.parse import urlencode
from aiogram import Bot, Dispatcher, types, executor
from aiogram.dispatcher import filters

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
API_URL = os.environ.get("API_URL", "http://localhost:8501")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher(bot)

@dp.message_handler(commands=["start"])
async def start_command(message: types.Message):
    await message.reply(
        "Hi! I'm your Card Pattern Analyzer Bot.\n\nSend me card numbers, one per line, and I'll analyze them for you.\n\n Use /upgrade to become premium and get unlimited access.\n\nTo view previous usages use /history"
    )

@dp.message_handler(filters.Text(startswith=["/upgrade", "/validate_payment","/history"], ignore_case=True) , commands=None )
async def handle_command(message: types.Message):
    if message.text.startswith("/upgrade"):
      await upgrade_command(message)
    elif message.text.startswith("/validate_payment"):
      await validate_payment_command(message)
    elif message.text.startswith("/history"):
      await history_command(message)

@dp.message_handler(commands=None)
async def check_card(message: types.Message):
    card_numbers = message.text.splitlines()
    telegram_id = message.from_user.id

    try:
        query_params = urlencode({"card_numbers": ",".join(card_numbers), "telegram_id": telegram_id})
        response = requests.get(f"{API_URL}?{query_params}")
        response.raise_for_status()
        data = response.json()
        
        msg = ""
        for result in data["results"]:
            if "error" in result:
                msg += f"Card Number: {result['card_number']}\n{result['error']}\n\n"
            else:
                msg += f"Card Number: {result['card_number']}\n"
                msg += f"  Is Valid: {result['is_valid']}\n"
                msg += f"  Network: {result['network']}\n\n"
        await message.reply(msg)
    except requests.exceptions.RequestException as e:
        await message.reply(f"An error occurred: {e}")


async def upgrade_command(message: types.Message):
    await message.reply("To upgrade to premium, please send $10 via PayPal to [PayPal email]. After paying use the /validate_payment command with transaction hash.")

async def validate_payment_command(message: types.Message):
    args = message.text.split()[1:]
    if not args:
        await message.reply("Please send payment hash after command. Ex. /validate_payment transaction_hash")
        return
    
    transaction_hash = " ".join(args)

    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, telegram_id FROM users WHERE telegram_id = ?", (message.from_user.id,))
    user = cursor.fetchone()
    if not user:
        conn.close()
        await message.reply("User Not found, Please Use /start command first")
        return

    user_id, telegram_id = user

    if transaction_hash.startswith("valid_payment_"):
        cursor.execute("UPDATE users SET subscription_tier = 'premium' WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        await message.reply("You have successfully upgraded to premium!")
    else:
        conn.close()
        await message.reply("Payment not validated! Please be sure to send the correct transaction hash and use valid payment methods.")

async def history_command(message: types.Message):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, telegram_id FROM users WHERE telegram_id = ?", (message.from_user.id,))
    user = cursor.fetchone()
    if not user:
        conn.close()
        await message.reply("User Not found, Please Use /start command first")
        return

    user_id, telegram_id = user

    cursor.execute("SELECT card_number, check_time FROM usage_log WHERE user_id = ? ORDER BY check_time DESC LIMIT 10", (user_id,))
    usage_history = cursor.fetchall()
    conn.close()

    if not usage_history:
        await message.reply("No history found")
        return

    msg = "Usage history for last 10 checks:\n\n"
    for card_number, check_time in usage_history:
        msg += f"Card Number: {card_number}\n"
        msg += f"Check Time: {check_time}\n\n"

    await message.reply(msg)

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
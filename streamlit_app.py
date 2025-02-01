import streamlit as st
import sqlite3
from datetime import datetime
import json
from typing import List
import requests
import os
import json
from urllib.parse import urlencode
import logging
import threading
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.dispatcher import filters

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Global variables
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
API_URL = os.environ.get("API_URL", "http://localhost:8501")
bot = None  # Initialize bot to None, updated on bot start.
dp = None # Initialize dispatcher to None, updated on bot start.
bot_running = False # Global flag to handle bot startup and shutdowns

# Database setup
def create_table():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            telegram_id INTEGER UNIQUE,
            subscription_tier TEXT DEFAULT 'free',
            daily_usage INTEGER DEFAULT 0,
            last_reset TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usage_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            card_number TEXT,
            check_time TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    ''')
    conn.commit()
    conn.close()

create_table()

# Card Checking logic (same as before)
def luhn_check(card_number: str) -> bool:
    card_number = "".join(filter(str.isdigit, card_number))
    if not card_number:
        return False
    n = len(card_number)
    if n < 13 or n > 19:
        return False

    sum_val = 0
    for i in range(n - 1, -1, -2):
        sum_val += int(card_number[i])
    for i in range(n - 2, -1, -2):
        d = int(card_number[i]) * 2
        if d > 9:
            d -= 9
        sum_val += d
    return sum_val % 10 == 0


def get_card_network(card_number: str) -> str:
    card_number = "".join(filter(str.isdigit, card_number))
    if not card_number:
        return "Invalid Card Number"
    
    if card_number.startswith(("34", "37")) and (len(card_number) == 15):
        return "American Express"
    if card_number.startswith(("4")) and (len(card_number) == 13 or len(card_number) == 16 or len(card_number) == 19):
        return "Visa"
    if card_number.startswith(("50", "51", "52", "53", "54", "55")) and (len(card_number) == 16):
        return "Mastercard"
    if card_number.startswith(("6011", "644", "645", "646", "647", "648", "649", "65")) and (len(card_number) == 16 or len(card_number) == 19):
            return "Discover"
    if card_number.startswith("35") and (len(card_number) in (15,16,17,18,19)):
        return "JCB"
    return "Unknown"

def check_user_usage(telegram_id: int, tier: str, free_limit: int = 5) -> bool:
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()

    cursor.execute("SELECT user_id, subscription_tier, daily_usage, last_reset FROM users WHERE telegram_id = ?", (telegram_id,))
    user = cursor.fetchone()
    
    if not user:
        cursor.execute("INSERT INTO users (telegram_id) VALUES (?)", (telegram_id,))
        conn.commit()
        user_id = cursor.lastrowid
        conn.close()
        return True

    user_id, subscription_tier, daily_usage, last_reset = user

    if subscription_tier == 'premium':
         conn.close()
         return True

    if last_reset:
        last_reset_dt = datetime.strptime(last_reset, "%Y-%m-%d %H:%M:%S.%f")
        if (datetime.now() - last_reset_dt).days >= 1:
            cursor.execute("UPDATE users SET daily_usage = 0, last_reset = ? WHERE telegram_id = ?", (datetime.now(), telegram_id))
            conn.commit()
            daily_usage = 0
    
    if daily_usage < free_limit:
        cursor.execute("UPDATE users SET daily_usage = ? WHERE telegram_id = ?", (daily_usage+1, telegram_id))
        conn.commit()
        conn.close()
        return True
    else:
        conn.close()
        return False

def log_card_check(user_id: int, card_number: str):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO usage_log (user_id, card_number) VALUES (?, ?)", (user_id, card_number))
    conn.commit()
    conn.close()

def check_cards(card_numbers: List[str], telegram_id: int):
    response = []
    
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, subscription_tier FROM users WHERE telegram_id = ?", (telegram_id,))
    user = cursor.fetchone()
    conn.close()
    
    if user:
        user_id, subscription_tier = user
        is_premium = True if subscription_tier == 'premium' else False
    else:
        is_premium = False

    for card_number in card_numbers:
        if is_premium or check_user_usage(telegram_id, subscription_tier):
            is_valid = luhn_check(card_number)
            network = get_card_network(card_number)
            response.append({
                "card_number": card_number,
                "is_valid": is_valid,
                "network": network,
            })
            if user:
                log_card_check(user_id, card_number)
        else:
            response.append({
                "card_number": card_number,
                "error": "You have exceeded your daily free usage. Upgrade to premium to check more cards"
            })

    return {"results": response}


# Telegram Bot Logic
async def start_command(message: types.Message):
    await message.reply(
        "Hi! I'm your Card Pattern Analyzer Bot.\n\nSend me card numbers, one per line, and I'll analyze them for you.\n\n Use /upgrade to become premium and get unlimited access.\n\nTo view previous usages use /history"
    )

async def handle_command(message: types.Message):
    if message.text.startswith("/upgrade"):
      await upgrade_command(message)
    elif message.text.startswith("/validate_payment"):
      await validate_payment_command(message)
    elif message.text.startswith("/history"):
      await history_command(message)

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

def run_telegram_bot():
    global bot, dp, bot_running
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    dp = Dispatcher(bot)

    dp.message_handler(commands=["start"])(start_command)
    dp.message_handler(filters.Text(startswith=["/upgrade", "/validate_payment","/history"], ignore_case=True) , commands=None )(handle_command)
    dp.message_handler(commands=None)(check_card)

    bot_running = True
    async def start_bot():
        await dp.start_polling()
    asyncio.run(start_bot())

def stop_telegram_bot():
    global bot, dp, bot_running
    if bot and dp:
      logging.info("Stopping Telegram bot...")
      async def stop_bot():
         await dp.stop_polling()
         await bot.session.close()
      asyncio.run(stop_bot())
      bot = None
      dp = None
    bot_running = False

def start_bot_thread():
  if not hasattr(st, 'bot_thread') or not st.bot_thread.is_alive() or not bot_running:
    st.bot_thread = threading.Thread(target=run_telegram_bot)
    st.bot_thread.daemon = True
    st.bot_thread.start()
    logging.info("Telegram bot started...")

# Streamlit App
def main():
    st.set_page_config(page_title="Card Checker API & Admin", page_icon="💳")
    st.title("Card Pattern Analyzer API & Admin")
    
    # Sidebar for admin controls
    with st.sidebar:
        st.header("Admin Panel")
        
        if st.button("Start Telegram Bot"):
            start_bot_thread()
        
        if st.button("Stop Telegram Bot"):
             stop_telegram_bot()

        st.write(f"Bot status : {'Running' if bot_running else 'Stopped'}")

    if st.experimental_get_query_params():
        try:
            card_numbers = st.experimental_get_query_params()["card_numbers"][0].split(",")
            telegram_id = int(st.experimental_get_query_params()["telegram_id"][0])
            
            results = check_cards(card_numbers, telegram_id)
            st.json(results)
        except Exception as e:
             st.error(f"Error: Invalid parameters: {e}")
    else:
        st.write("Send a GET request with card_numbers and telegram_id as parameters to / for using this API")

    st.header("User Management")
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users")
    users = cursor.fetchall()
    conn.close()
    
    if users:
      st.dataframe(users)
    else:
      st.write("No Users found")

    st.header("Usage Management")
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM usage_log")
    usage = cursor.fetchall()
    conn.close()

    if usage:
      st.dataframe(usage)
    else:
       st.write("No usages found")

    start_bot_thread()

if __name__ == "__main__":
    main()
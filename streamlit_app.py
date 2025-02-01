# streamlit_app.py
import streamlit as st
import sqlite3
from datetime import datetime
import json
from typing import List
import requests
import os
import json
from urllib.parse import urlencode

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

# Streamlit App
def main():
    st.set_page_config(page_title="Card Checker API", page_icon="💳")
    
    st.title("Card Pattern Analyzer API")

    # run the telegram bot
    os.system("python telegram_bot.py &")
    
    if st.experimental_get_query_params():
        try:
            card_numbers = st.experimental_get_query_params()["card_numbers"][0].split(",")
            telegram_id = int(st.experimental_get_query_params()["telegram_id"][0])
            
            results = check_cards(card_numbers, telegram_id)
            st.json(results)
        except Exception as e:
             st.error(f"Error: Invalid parameters: {e}")
    else:
        st.write("Send a POST request with the JSON payload to /api/check-cards for using this API")


if __name__ == "__main__":
    main()
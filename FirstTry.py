import os
import telebot
import requests
import numpy as np
import time
import threading
from telebot import types

# 🔑 Токен
# 1. На Render укажи TELEGRAM_TOKEN в переменных окружения.
# 2. Локально бот возьмёт токен, прописанный вторым аргументом.
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8250034607:AAEWwZMF4awfu3jykjOpqXcuH32eYj562mk")
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# ========= ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ =========
CACHE = []
LAST_UPDATE = 0
LOCK = threading.Lock()

# ========= ФУНКЦИИ =========

def safe_request(url, params=None, retries=3):
    """Безопасный запрос к API с повтором"""
    for i in range(retries):
        try:
            r = requests.get(url, params=params, timeout=10)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            print(f"⚠️ Ошибка запроса {url}: {e}, попытка {i+1}")
            time.sleep(1)
    return None

def calculate_RSI(prices, period=14):
    """Вычисляем RSI"""
    prices = np.array(prices, dtype=float)
    if len(prices) < period:
        return 50.0

    deltas = np.diff(prices)
    seed = deltas[:period]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    rs = up / down if down != 0 else 0
    rsi = np.zeros_like(prices)
    rsi[:period] = 100. - 100. / (1. + rs)

    for i in range(period, len(prices)):
        delta = deltas[i - 1]
        upval = max(delta, 0)
        downval = -min(delta, 0)
        up = (up * (period - 1) + upval) / period
        down = (down * (period - 1) + downval) / period
        rs = up / down if down != 0 else 0
        rsi[i] = 100. - 100. / (1. + rs)

    return float(rsi[-1])

def get_top_symbols(limit=150):
    """Получаем топ-150 USDT-пар с Binance по объёму"""
    data = safe_request("https://api.binance.com/api/v3/ticker/24hr")
    if not data:
        print("❌ Не удалось получить данные с Binance")
        return []

    usdt_pairs = [coin for coin in data if coin.get("symbol", "").endswith("USDT")]
    try:
        sorted_pairs = sorted(usdt_pairs, key=lambda x: float(x.get("quoteVolume", 0)), reverse=True)
    except Exception as e:
        print("❌ Ошибка сортировки:", e)
        return []

    return sorted_pairs[:limit]

def update_cache():
    """Обновление кеша монет"""
    global CACHE, LAST_UPDATE
    print("♻️ Обновление данных...")

    symbols = get_top_symbols(150)
    if not symbols:
        print("⚠️ Нет данных для кеша")
        return

    results = []

    for coin in symbols:
        symbol = coin.get("symbol")
        if not symbol:
            continue

        try:
            url = "https://api.binance.com/api/v3/klines"
            params = {"symbol": symbol, "interval": "1h", "limit": 30}
            data = safe_request(url, params)
            if not data:
                continue

            closes = []
            for c in data:
                if len(c) > 4:
                    try:
                        closes.append(float(c[4]))
                    except ValueError:
                        continue

            if len(closes) < 15:
                continue

            rsi = calculate_RSI(closes)

            results.append({
                "symbol": symbol,
                "rsi": round(rsi, 2),
                "price": round(closes[-1], 4),
                "volume": float(coin.get("quoteVolume", 0))
            })

            time.sleep(0.05)
        except Exception as e:
            print(f"⚠️ Ошибка для {symbol}: {e}")
            continue

    results = sorted(results, key=lambda x: x["rsi"])
    with LOCK:
        CACHE = results
        LAST_UPDATE = time.time()
    print("✅ Данные обновлены, монет:", len(CACHE))

def cache_updater():
    """Фоновое обновление каждые 5 минут"""
    while True:
        try:
            update_cache()
        except Exception as e:
            print("⚠️ Ошибка в потоке обновления кеша:", e)
        time.sleep(300)

# ========= ОБРАБОТЧИКИ =========

@bot.message_handler(commands=['start'])
def start_message(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn1 = types.KeyboardButton("🔥 Интересные монеты")
    btn2 = types.KeyboardButton("ℹ️ О боте")
    btn3 = types.KeyboardButton("📊 Последнее обновление")
    markup.add(btn1, btn2, btn3)

    text = (
        "👋 Привет! Я бот для анализа крипторынка.\n\n"
        "Что я умею:\n"
        "1) Постоянно анализирую топ-150 монет по объёму на Binance.\n"
        "2) Считаю RSI по 1-часовым свечам.\n"
        "3) Показываю топ-10 монет с самым низким RSI.\n\n"
        "Выбирай действие кнопкой ниже 👇"
    )
    bot.send_message(message.chat.id, text, reply_markup=markup)

@bot.message_handler(func=lambda message: True)
def handle_buttons(message):
    if message.text == "🔥 Интересные монеты":
        interesting_message(message)
    elif message.text == "ℹ️ О боте":
        bot.send_message(message.chat.id, "Я использую данные Binance и RSI-анализ для поиска монет 🚀")
    elif message.text == "📊 Последнее обновление":
        with LOCK:
            if LAST_UPDATE == 0:
                bot.send_message(message.chat.id, "❌ Данных пока нет.")
            else:
                bot.send_message(message.chat.id, f"🕒 Последнее обновление кеша: {time.ctime(LAST_UPDATE)}")

def interesting_message(message):
    with LOCK:
        if not CACHE:
            bot.send_message(message.chat.id, "⚠️ Данные ещё не загружены, попробуй через минуту...")
            return
        coins = CACHE[:10]

    text = "🔥 Топ-10 монет с самым низким RSI:\n\n"
    for c in coins:
        if c['rsi'] < 30:
            mood = "🟢 (перепродан)"
        elif c['rsi'] > 70:
            mood = "🔴 (перекуплен)"
        else:
            mood = "🟡 (нейтрал)"
        text += f"• {c['symbol']}\n"
        text += f"   💵 Цена: ${c['price']}\n"
        text += f"   📉 RSI: {c['rsi']} {mood}\n"
        text += f"   📊 Объём: {c['volume']:,}\n\n"
    bot.send_message(message.chat.id, text)

# ========= ЗАПУСК =========
if __name__ == "__main__":
    print("🚀 Бот запущен...")

    update_cache()  # первое обновление кеша

    updater_thread = threading.Thread(target=cache_updater, daemon=True)
    updater_thread.start()

    while True:
        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except Exception as e:
            print("❌ Ошибка polling:", e)
            time.sleep(5)

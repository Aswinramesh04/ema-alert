import requests
import smtplib
import requests
import time
import json
from datetime import datetime, timedelta

# ============================================================================
# CONFIGURATION - UPDATE THESE VALUES
# ============================================================================

import os
from dotenv import load_dotenv

# Load variables from .env for local development
load_dotenv()

# Telegram Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
# Indicator Configuration
EMA_FAST = 9
EMA_SLOW = 15
TIMEFRAME_MINUTES = int(os.getenv("TIMEFRAME_MINUTES", "1"))  # Candle timeframe in minutes

# Market Data Configuration (Binance 1m candles)
BINANCE_API_URL = "https://api.binance.com"
SYMBOLS = [
    {"api_symbol": "BTCUSDT", "label": "BTC/USD"},
    {"api_symbol": "SOLUSDT", "label": "SOL/USD"},
    {"api_symbol": "ETHUSDT", "label": "ETH/USD"}
]  # Trading pairs used for EMA calculation
BINANCE_INTERVAL = "1m"      # Candle interval; keep "1m" to match TIMEFRAME_MINUTES = 1

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def calculate_ema(prices, period):
    """
    Calculate Exponential Moving Average
    prices: list of prices (oldest to newest)
    period: EMA period
    """
    if len(prices) < period:
        return None
    
    multiplier = 2 / (period + 1)
    ema = sum(prices[:period]) / period  # SMA for first value
    
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
    
    return ema

def fetch_btc_ohlc_data(symbol, interval="1m", limit=500):
    """Fetch OHLC data from Binance klines for a given symbol.

    Returns: list of [timestamp, open, high, low, close]
    """
    # try:
    #     endpoint = f"{BINANCE_API_URL}/api/v3/klines"

    #     params = {
    #         "symbol": BINANCE_SYMBOL,
    #         "interval": BINANCE_INTERVAL,
    #         "limit": limit,  # number of candles to fetch
    #     }

    #     response = requests.get(endpoint, params=params, timeout=10)
    #     response.raise_for_status()

    #     raw = response.json()

    #     # Binance kline format:
    #     # [
    #     #   openTime, open, high, low, close, volume,
    #     #   closeTime, quoteAssetVolume, numberOfTrades,
    #     #   takerBuyBaseVolume, takerBuyQuoteVolume, ignore
    #     # ]
    #     ohlc = []
    #     for k in raw:
    #         timestamp = k[0]
    #         open_price = float(k[1])
    #         high = float(k[2])
    #         low = float(k[3])
    #         close = float(k[4])
    #         ohlc.append([timestamp, open_price, high, low, close])

    #     return ohlc


    endpoint = f"{BINANCE_API_URL}/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    resp = requests.get(endpoint, params=params, timeout=10)
    resp.raise_for_status()
    raw = resp.json()
    ohlc = []
    for k in raw:
        timestamp = k[0]
        open_price = float(k[1])
        high = float(k[2])
        low = float(k[3])
        close = float(k[4])
        ohlc.append([timestamp, open_price, high, low, close])

    return ohlc

def send_email_alert(subject, body, ema_fast, ema_slow, direction):
    """Send Telegram alert for EMA crossover (replaces email)."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ Telegram Error: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is not set.")
        return False

    try:
        text = (
            f"{subject}\n\n"
            f"Signal: {direction.upper()}\n"
            f"EMA(9): {ema_fast:.2f}\n"
            f"EMA(15): {ema_slow:.2f}\n"
            f"Timeframe: {TIMEFRAME_MINUTES}-minute\n"
            f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown",
        }

        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()

        print(f"✅ Telegram alert sent! | {direction.upper()} | EMA(9): ${ema_fast:.2f} | EMA(15): ${ema_slow:.2f}")
        return True

    except requests.exceptions.RequestException as e:
        print(f"❌ Telegram Error: {e}")
        return False

def check_ema_crossover(prices_list):
    """
    Check for EMA crossover
    Returns: 'bullish' (9 > 15), 'bearish' (9 < 15), or None
    """
    if len(prices_list) < EMA_SLOW + 5:  # Need enough data for both EMAs
        return None, None, None
    
    # Calculate current EMAs (using last EMA_SLOW + 5 candles for stability)
    recent_prices = prices_list[-(EMA_SLOW + 5):]
    
    ema_fast_current = calculate_ema(recent_prices, EMA_FAST)
    ema_slow_current = calculate_ema(recent_prices, EMA_SLOW)
    
    if ema_fast_current is None or ema_slow_current is None:
        return None, ema_fast_current, ema_slow_current
    
    # Calculate previous candle EMAs (one candle back)
    prev_prices = prices_list[-(EMA_SLOW + 6):-1]
    
    if len(prev_prices) < EMA_SLOW:
        ema_fast_prev = None
        ema_slow_prev = None
    else:
        ema_fast_prev = calculate_ema(prev_prices, EMA_FAST)
        ema_slow_prev = calculate_ema(prev_prices, EMA_SLOW)
    
    # Detect crossover
    crossover = None
    
    if ema_fast_prev is not None and ema_slow_prev is not None:
        # Bullish crossover: EMA9 crosses above EMA15
        if ema_fast_prev <= ema_slow_prev and ema_fast_current > ema_slow_current:
            crossover = 'bullish'
        
        # Bearish crossover: EMA9 crosses below EMA15
        elif ema_fast_prev >= ema_slow_prev and ema_fast_current < ema_slow_current:
            crossover = 'bearish'

    # Debug output for EMA values each check
    prev_fast_str = f"{ema_fast_prev:.6f}" if ema_fast_prev is not None else "N/A"
    prev_slow_str = f"{ema_slow_prev:.6f}" if ema_slow_prev is not None else "N/A"
    curr_fast_str = f"{ema_fast_current:.6f}" if ema_fast_current is not None else "N/A"
    curr_slow_str = f"{ema_slow_current:.6f}" if ema_slow_current is not None else "N/A"
    print(
        f"DEBUG EMA | prev_fast={prev_fast_str} prev_slow={prev_slow_str} "
        f"curr_fast={curr_fast_str} curr_slow={curr_slow_str} crossover={crossover}"
    )

    return crossover, ema_fast_current, ema_slow_current

# ============================================================================
# MAIN MONITORING LOOP
# ============================================================================

def main():
    """
    Main monitoring loop - runs continuously
    """
    print("=" * 70)
    print("🚀 BTC/USD EMA(9,15) Crossover Alert System Started")
    print("=" * 70)
    # print(f"📧 Email: {ALERT_RECIPIENT}")
    print(f"📊 Timeframe: {TIMEFRAME_MINUTES} minutes")
    print(f"📈 Indicators: EMA({EMA_FAST}) and EMA({EMA_SLOW})")
    print("=" * 70)
    print()
    
    # Track last alert per symbol to avoid duplicate alerts
    sleep_seconds = TIMEFRAME_MINUTES * 60
    last_alert_timestamp = {}  # key: label or api_symbol

    while True:
        now = datetime.now()
        for cfg in SYMBOLS:
            api_symbol = cfg["api_symbol"]
            label = cfg["label"]

            print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] Fetching data for {label} ({api_symbol})...")

            ohlc = fetch_btc_ohlc_data(api_symbol, BINANCE_INTERVAL)
            if not ohlc:
                continue

            close_prices = [c[4] for c in ohlc]
            crossover, ema_9, ema_15 = check_ema_crossover(close_prices)

            if crossover and ema_9 is not None and ema_15 is not None:
                last_ts = last_alert_timestamp.get(api_symbol)
                if last_ts is None or (now - last_ts).total_seconds() > sleep_seconds:
                    subject = f"🚨 {label} EMA Crossover Alert - {crossover.upper()}"
                    body = f"{label} EMA(9) has crossed {'above' if crossover == 'bullish' else 'below'} EMA(15)"
                    send_email_alert(subject, body, ema_9, ema_15, crossover)
                    last_alert_timestamp[api_symbol] = now

            # Optional: print per‑symbol status
            ema_9_str = f"{ema_9:.2f}" if ema_9 is not None else "N/A"
            ema_15_str = f"{ema_15:.2f}" if ema_15 is not None else "N/A"
            print(f"{label} | EMA(9): ${ema_9_str} | EMA(15): ${ema_15_str}")

        print(f"Waiting {TIMEFRAME_MINUTES} minutes before next multi‑symbol scan...")
        time.sleep(sleep_seconds)
                

if __name__ == "__main__":
    main()
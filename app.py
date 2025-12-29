import requests
import smtplib
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

#########################
# Telegram Configuration #
#########################
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
# Indicator Configuration
EMA_FAST = 9
EMA_SLOW = 15
TIMEFRAME_MINUTES = int(os.getenv("TIMEFRAME_MINUTES", "1"))  # Candle timeframe in minutes

####################################
# Market Data Configuration
####################################

# Twelve Data for FX / metals / commodities
TWELVEDATA_API_URL = "https://api.twelvedata.com/time_series"
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY")
TWELVEDATA_INTERVAL = os.getenv("TWELVEDATA_INTERVAL", "1min")  # e.g. 1min, 5min, 15min

# Unified symbol list with provider
SYMBOLS = [
    # Crypto via Twelve Data
    {"provider": "twelvedata", "api_symbol": "BTC/USD", "label": "BTC/USD"},
    {"provider": "twelvedata", "api_symbol": "SOL/USD", "label": "SOL/USD"},
    {"provider": "twelvedata", "api_symbol": "ETH/USD", "label": "ETH/USD"},

    # FX via Twelve Data
    {"provider": "twelvedata", "api_symbol": "USD/JPY", "label": "USDJPY"},
    {"provider": "twelvedata", "api_symbol": "GBP/USD", "label": "GBPUSD"},
    {"provider": "twelvedata", "api_symbol": "AUD/USD", "label": "AUDUSD"},
    {"provider": "twelvedata", "api_symbol": "EUR/USD", "label": "EURUSD"},

    # Metals via Twelve Data
    {"provider": "twelvedata", "api_symbol": "XAU/USD", "label": "XAU/USD"},
]  # All pairs used for EMA calculation

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


def fetch_twelvedata_ohlc(symbol, interval="1min", limit=500):
    """Fetch OHLC data from Twelve Data for a given symbol.

    Returns: list of [timestamp, open, high, low, close]
    """
    if not TWELVEDATA_API_KEY:
        print("❌ Twelve Data Error: TWELVEDATA_API_KEY is not set.")
        return None

    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": limit,
        "apikey": TWELVEDATA_API_KEY,
    }

    resp = requests.get(TWELVEDATA_API_URL, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    if "values" not in data:
        print(f"❌ Twelve Data Error for {symbol}: {data}")
        return None

    values = data["values"]

    # Twelve Data returns newest first; reverse to oldest → newest
    values = list(reversed(values))

    ohlc = []
    for v in values:
        # datetime like '2024-01-01 12:34:00'
        ts_str = v.get("datetime")
        try:
            dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
            timestamp = int(dt.timestamp() * 1000)
        except Exception:
            timestamp = ts_str

        open_price = float(v["open"])
        high = float(v["high"])
        low = float(v["low"])
        close = float(v["close"])
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
            provider = cfg.get("provider", "binance")

            print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] Fetching data for {label} ({api_symbol}) from {provider}...")

            if provider == "twelvedata":
                ohlc_data = fetch_twelvedata_ohlc(api_symbol, TWELVEDATA_INTERVAL)
            else:
                print(f"Unknown provider '{provider}' for {label}. Skipping.")
                continue

            if not ohlc_data or len(ohlc_data) < EMA_SLOW + 5:
                print(f"Not enough data received for {label}. Skipping this symbol.")
                continue

            closes = [candle[4] for candle in ohlc_data]

            crossover, ema_fast, ema_slow = check_ema_crossover(closes)

            if crossover and ema_fast is not None and ema_slow is not None:
                last_ts = last_alert_timestamp.get(api_symbol)
                if last_ts is None or (now - last_ts).total_seconds() > sleep_seconds:
                    subject = f"🚨 {label} EMA Crossover Alert - {crossover.upper()}"
                    body = f"{label} EMA(9) has crossed {'above' if crossover == 'bullish' else 'below'} EMA(15)"
                    send_email_alert(subject, body, ema_fast, ema_slow, crossover)
                    last_alert_timestamp[api_symbol] = now

            # Optional: print per‑symbol status
            ema_fast_str = f"{ema_fast:.2f}" if ema_fast is not None else "N/A"
            ema_slow_str = f"{ema_slow:.2f}" if ema_slow is not None else "N/A"
            print(f"{label} | EMA(9): ${ema_fast_str} | EMA(15): ${ema_slow_str}")

        print(f"Waiting {TIMEFRAME_MINUTES} minutes before next multi‑symbol scan...")
        time.sleep(sleep_seconds)
                

if __name__ == "__main__":
    main()
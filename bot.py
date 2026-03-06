import pandas as pd
import numpy as np
import requests
import mplfinance as mpf
from binance import ThreadedWebsocketManager
from binance.client import Client
from flask import Flask
import threading

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running ✅"

def run_web():
    app.run(host="0.0.0.0", port=10000)

# запускаємо веб сервер у окремому потоці
threading.Thread(target=run_web).start()

# ---------------- CONFIG ----------------
SYMBOL = "ETHUSDT"
INTERVAL = "1h"  # для тесту в реальному часі, можна змінити на "1h"
TELEGRAM_TOKEN = "8569058141:AAGjUVh4eoYvX8RumLZGfm5FVIGOtYSZaDk"
CHAT_ID = "830027758"

client = Client()
data = []
signals_history = []  # Історія всіх сигналів PPR

# ---------------- TELEGRAM ----------------
def send_photo(path, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    files = {"photo": open(path, "rb")}
    payload = {"chat_id": CHAT_ID, "caption": text}
    requests.post(url, data=payload, files=files)

# ---------------- PPR PATTERN ----------------
def detect_pattern(df):
    if len(df) < 3:
        return None

    c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]

    body1 = abs(c1.close - c1.open)
    body2 = abs(c2.close - c2.open)
    if body1 <= body2:
        return None

    if not (c2.high > c1.high and c2.high > c3.high):
        return None

    body_high_2, body_low_2 = max(c2.open, c2.close), min(c2.open, c2.close)
    body_high_3, body_low_3 = max(c3.open, c3.close), min(c3.open, c3.close)
    if not (body_high_3 >= body_high_2 and body_low_3 <= body_low_2):
        return None

    direction = None
    if c2.close > c2.open and c3.close < c3.open:
        direction = "SHORT"
    elif c2.close < c2.open and c3.close > c3.open:
        direction = "LONG"
    else:
        return None

    entry = c3.close
    if direction == "LONG":
        stop = c2.low - 3
        risk = entry - stop
        tp1 = entry + risk
        tp2 = entry + risk*2
    else:
        stop = c2.high + 3
        risk = stop - entry
        tp1 = entry - risk
        tp2 = entry - risk*2

    risk_percent = (risk / entry) * 100
    return direction, entry, stop, tp1, tp2, risk_percent

# ---------------- CHART WITH SIGNALS ----------------
def send_chart(df, signal=None):
    df_plot = df.copy()
    if "time" in df_plot.columns and pd.api.types.is_integer_dtype(df_plot["time"]):
        df_plot["time"] = pd.to_datetime(df_plot["time"], unit="ms")

    # беремо останні 50 свічок для графіка
    df_plot = df_plot.tail(50)
    df_plot.set_index("time", inplace=True)

    # підсвічування сигналів
    long_markers = [np.nan]*len(df_plot)
    short_markers = [np.nan]*len(df_plot)

    for sig in signals_history:
        idx = sig['index']
        if idx >= len(df) - 50:  # відносний індекс у останніх 50 свічках
            rel_idx = idx - (len(df) - 50)
            if sig['direction'] == "LONG":
                long_markers[rel_idx] = sig['entry']
            else:
                short_markers[rel_idx] = sig['entry']

    add_plots = []
    if any(not np.isnan(x) for x in long_markers):
        add_plots.append(mpf.make_addplot(long_markers, type='scatter', markersize=100, marker='^', color='green'))
    if any(not np.isnan(x) for x in short_markers):
        add_plots.append(mpf.make_addplot(short_markers, type='scatter', markersize=100, marker='v', color='red'))

    file = "chart.png"
    mpf.plot(
        df_plot,
        type="candle",
        style="binance",
        title=f"{SYMBOL} PPR Signals",
        addplot=add_plots,
        savefig=file
    )

    if signal:
        direction, entry, stop, tp1, tp2, risk_percent = signal
        message = (
            f"{SYMBOL} SIGNAL\n\n"
            f"Direction: {direction}\n"
            f"Entry: {round(entry,2)}\n"
            f"Stop: {round(stop,2)}\n"
            f"TP1: {round(tp1,2)}\n"
            f"TP2: {round(tp2,2)}\n"
            f"Risk: {round(risk_percent,2)}%\n"
            f"RR: 1:2"
        )
    else:
        message = f"{SYMBOL} – поточний графік з усіма минулими сигналами PPR"

    send_photo(file, message)

# ---------------- INITIAL CHART ----------------
def send_initial_chart():
    global data
    klines = client.get_klines(symbol=SYMBOL, interval=INTERVAL, limit=50)
    df_init = pd.DataFrame(klines, columns=[
        "time","open","high","low","close","volume","close_time",
        "quote_asset_volume","number_of_trades","taker_buy_base","taker_buy_quote","ignore"
    ])
    df_init = df_init[["time","open","high","low","close"]]
    for col in ["open","high","low","close"]:
        df_init[col] = df_init[col].astype(float)
    data = df_init.to_dict('records')
    send_chart(df_init)

# ---------------- WEBSOCKET ----------------
def handle_socket(msg):
    if msg["e"] != "kline":
        return
    kline = msg["k"]
    if not kline["x"]:
        return
    candle = {
        "time": kline["t"],
        "open": float(kline["o"]),
        "high": float(kline["h"]),
        "low": float(kline["l"]),
        "close": float(kline["c"])
    }
    data.append(candle)
    if len(data) < 10:
        return
    df = pd.DataFrame(data)
    signal = detect_pattern(df)
    if signal is not None:
        idx = len(df)-1
        direction, entry, stop, tp1, tp2, risk_percent = signal
        signals_history.append({"index": idx, "direction": direction, "entry": entry})
        print("----------")
        print(f"Патерн знайдено! Напрямок: {direction}")
        print(f"Entry: {entry}, Stop: {stop}, TP1: {tp1}, TP2: {tp2}, Risk %: {risk_percent:.2f}")
        send_chart(df, signal)
    else:
        print("Патерн не знайдено")

# ---------------- START ----------------
send_initial_chart()  # стартовий графік перед WebSocket

twm = ThreadedWebsocketManager()
twm.start()
twm.start_kline_socket(callback=handle_socket, symbol=SYMBOL, interval=Client.KLINE_INTERVAL_1HOUR)
twm.join()
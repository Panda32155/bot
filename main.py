from flask import Flask
import threading
from bot import start_bot

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot running ✅"

def run_bot():
    start_bot()

# запускаємо бота у фоновому потоці
threading.Thread(target=run_bot).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
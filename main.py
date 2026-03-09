from flask import Flask
import requests, threading, time, json
import websocket

app = Flask(__name__)

BOT_TOKEN = "8546209847:AAFb6fa0yJBa5iQNWvE32p-rA8nwcrFlGfY"
CHAT_ID = "1603606771"
WS_URL = "wss://pumpportal.fun/api/data"
MIN_SAFE_SCORE = 60

def send_tele(msg):
    try:
        requests.post(
            "https://api.telegram.org/bot"+BOT_TOKEN+"/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except:
        pass

def calc_rug_score(data):
    score = 0
    if not data.get("twitter"):
        score += 20
    if not data.get("telegram"):
        score += 15
    if not data.get("website"):
        score += 10
    desc = str(data.get("description", ""))
    if not desc or len(desc) < 10:
        score += 15
    sol_amount = data.get("solAmount", 0)
    if isinstance(sol_amount, (int, float)):
        sol = sol_amount / 1e9 if sol_amount > 1000 else sol_amount
        if sol > 10:
            score += 30
        elif sol > 5:
            score += 20
        elif sol > 2:
            score += 10
    return min(score, 100)

def analyze_token(data):
    try:
        rug_score = calc_rug_score(data)
        safe_score = 100 - rug_score
        if safe_score < MIN_SAFE_SCORE:
            return
        name = data.get("name", "Unknown")
        symbol = data.get("symbol", "???")
        mint = data.get("mint", "")
        desc = data.get("description", "")
        desc_short = desc[:100] if desc else "-"
        has_twitter = "✅" if data.get("twitter") else "❌"
        has_telegram = "✅" if data.get("telegram") else "❌"
        has_website = "✅" if data.get("website") else "❌"
        sol_amount = data.get("solAmount", 0)
        if isinstance(sol_amount, (int, float)):
            sol = sol_amount / 1e9 if sol_amount > 1000 else sol_amount
            sol_display = str(round(sol, 3))
        else:
            sol_display = "?"
        if safe_score >= 80:
            risk_emoji = "🟢"
            risk_label = "LOW RISK"
        else:
            risk_emoji = "🟡"
            risk_label = "MEDIUM RISK"
        msg = ("🚀 <b>NEW TOKEN DETECTED!</b>\n"
               "━━━━━━━━━━━━━━\n"
               "📌 Name: <b>"+name+"</b>\n"
               "💎 Symbol: <b>$"+symbol+"</b>\n"
               "━━━━━━━━━━━━━━\n"
               +risk_emoji+" <b>Safe Score: "+str(safe_score)+"/100</b> ("+risk_label+")\n"
               "━━━━━━━━━━━━━━\n"
               "🐦 Twitter: "+has_twitter+"\n"
               "💬 Telegram: "+has_telegram+"\n"
               "🌐 Website: "+has_website+"\n"
               "📝 Desc: "+desc_short+"\n"
               "━━━━━━━━━━━━━━\n"
               "💰 Dev Buy: "+sol_display+" SOL\n"
               "🔗 pump.fun/"+mint)
        send_tele(msg)
    except Exception as e:
        print("analyze error:", str(e))

def on_message(ws, message):
    try:
        data = json.loads(message)
        if data.get("txType") == "create":
            threading.Thread(target=analyze_token, args=(data,), daemon=True).start()
    except:
        pass

def on_open(ws):
    print("WS connected")
    ws.send(json.dumps({"method": "subscribeNewToken"}))
    send_tele("🟢 <b>PumpFun Scanner AKTIF!</b>\nMonitoring token baru di pump.fun real-time...")

def on_error(ws, error):
    print("WS error:", str(error))

def on_close(ws, close_status_code, close_msg):
    print("WS closed, reconnecting...")

def run_scanner():
    while True:
        try:
            ws = websocket.WebSocketApp(
                WS_URL,
                on_message=on_message,
                on_open=on_open,
                on_error=on_error,
                on_close=on_close
            )
            ws.run_forever(ping_interval=30, ping_timeout=10)
        except Exception as e:
            print("Scanner error:", str(e))
        time.sleep(5)

threading.Thread(target=run_scanner, daemon=True).start()

@app.route("/")
def home():
    return "PumpFun Scanner Running! 🚀", 200
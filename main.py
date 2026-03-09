from flask import Flask
import requests, threading, time, json
import websocket

app = Flask(__name__)

BOT_TOKEN = "8546209847:AAFb6fa0yJBa5iQNWvE32p-rA8nwcrFlGfY"
CHAT_ID = "1603606771"
WS_URL = "wss://pumpportal.fun/api/data"

stats = {"win": 0, "loss": 0}
monitored_tokens = {}  # mint -> {"initial_mcap": x, "deadline": t, "name": n, "symbol": s}

def send_tele(msg):
    try:
        requests.post(
            "https://api.telegram.org/bot"+BOT_TOKEN+"/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except:
        pass

def get_winrate():
    total = stats["win"] + stats["loss"]
    if total == 0:
        return "N/A"
    pct = round(stats["win"] / total * 100, 1)
    return str(pct)+"% ("+str(stats["win"])+"W/"+str(stats["loss"])+"L)"

def fetch_metadata(uri):
    try:
        if not uri:
            return {}
        r = requests.get(uri, timeout=5)
        return r.json()
    except:
        return {}

def monitor_token_price(mint, initial_mcap, name, symbol):
    deadline = time.time() + 1800  # 30 minutes
    ws_monitor = None

    def on_msg(ws, message):
        nonlocal deadline
        try:
            data = json.loads(message)
            mcap = data.get("marketCapSol", 0)
            if mcap <= 0:
                return
            if mcap >= initial_mcap * 2:
                stats["win"] += 1
                send_tele("✅ <b>PUMP! 2x HIT!</b>\n"
                          "Token: <b>"+name+"</b> ($"+symbol+")\n"
                          "MC Awal: "+str(round(initial_mcap,2))+" SOL\n"
                          "MC Sekarang: "+str(round(mcap,2))+" SOL\n\n"
                          "📊 Win Rate: "+get_winrate())
                ws.close()
            elif mcap <= initial_mcap * 0.5:
                stats["loss"] += 1
                send_tele("❌ <b>DUMP! -50% HIT!</b>\n"
                          "Token: <b>"+name+"</b> ($"+symbol+")\n"
                          "MC Awal: "+str(round(initial_mcap,2))+" SOL\n"
                          "MC Sekarang: "+str(round(mcap,2))+" SOL\n\n"
                          "📊 Win Rate: "+get_winrate())
                ws.close()
            elif time.time() > deadline:
                ws.close()
        except:
            pass

    def on_open_monitor(ws):
        ws.send(json.dumps({"method": "subscribeTokenTrade", "keys": [mint]}))

    def run():
        try:
            ws = websocket.WebSocketApp(WS_URL, on_message=on_msg, on_open=on_open_monitor)
            ws.run_forever()
        except:
            pass

    threading.Thread(target=run, daemon=True).start()

def analyze_token(data):
    try:
        name = data.get("name", "Unknown")
        symbol = data.get("symbol", "???")
        mint = data.get("mint", "")
        uri = data.get("uri", "")
        initial_mcap = data.get("marketCapSol", 0)

        meta = fetch_metadata(uri)
        twitter = meta.get("twitter") or data.get("twitter") or ""
        telegram = meta.get("telegram") or data.get("telegram") or ""
        website = meta.get("website") or data.get("website") or ""
        description = meta.get("description") or data.get("description") or ""

        sol_amount = data.get("solAmount", 0)
        if isinstance(sol_amount, (int, float)):
            sol = sol_amount / 1e9 if sol_amount > 1000 else sol_amount
        else:
            sol = 0

        rug_score = 0
        if not twitter: rug_score += 15
        if not telegram: rug_score += 10
        if not website: rug_score += 5
        if not description or len(description) < 10: rug_score += 10
        if sol > 10: rug_score += 40
        elif sol > 5: rug_score += 25
        elif sol > 2: rug_score += 15
        elif sol > 0.5: rug_score += 5
        rug_score = min(rug_score, 100)
        safe_score = 100 - rug_score

        if safe_score >= 70:
            risk_emoji = "🟢"
            risk_label = "LOW RISK"
        elif safe_score >= 50:
            risk_emoji = "🟡"
            risk_label = "MEDIUM RISK"
        else:
            risk_emoji = "🔴"
            risk_label = "HIGH RISK"

        has_twitter = "✅ "+twitter if twitter else "❌"
        has_telegram = "✅ "+telegram if telegram else "❌"
        has_website = "✅ "+website if website else "❌"
        desc_short = description[:80]+"..." if len(description) > 80 else (description or "-")
        sol_display = str(round(sol, 4)) if sol > 0 else "0"
        mcap_display = str(round(initial_mcap, 2)) if initial_mcap else "?"

        msg = ("🚀 <b>NEW TOKEN DETECTED!</b>\n"
               "━━━━━━━━━━━━━━\n"
               "📌 <b>"+name+"</b> ($"+symbol+")\n"
               "━━━━━━━━━━━━━━\n"
               +risk_emoji+" <b>Safe Score: "+str(safe_score)+"/100</b> — "+risk_label+"\n"
               "━━━━━━━━━━━━━━\n"
               "🐦 Twitter: "+has_twitter+"\n"
               "💬 Telegram: "+has_telegram+"\n"
               "🌐 Website: "+has_website+"\n"
               "📝 "+desc_short+"\n"
               "━━━━━━━━━━━━━━\n"
               "💰 Dev Buy: "+sol_display+" SOL\n"
               "📊 Market Cap: "+mcap_display+" SOL\n"
               "🔗 pump.fun/"+mint+"\n"
               "━━━━━━━━━━━━━━\n"
               "📈 Win Rate: "+get_winrate()+"\n"
               "⏱ Monitoring 30 menit...")
        send_tele(msg)

        if mint and initial_mcap > 0:
            threading.Thread(target=monitor_token_price, args=(mint, initial_mcap, name, symbol), daemon=True).start()

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
    print("WS connected, subscribing...")
    ws.send(json.dumps({"method": "subscribeNewToken"}))
    send_tele("🟢 <b>PumpFun Scanner AKTIF!</b>\nMonitoring semua token baru di pump.fun...\n✅ Win/Loss tracking aktif (TP: 2x | SL: -50%)")

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
    wr = get_winrate()
    total = stats["win"] + stats["loss"]
    return "PumpFun Scanner | Signals: "+str(total)+" | Win Rate: "+wr, 200
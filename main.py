from flask import Flask
import requests, threading, time, json
import websocket

app = Flask(__name__)

BOT_TOKEN = "8546209847:AAFb6fa0yJBa5iQNWvE32p-rA8nwcrFlGfY"
CHAT_ID = "1603606771"
WS_URL = "wss://pumpportal.fun/api/data"

stats = {"win": 0, "loss": 0}
sol_price_usd = {"price": 130.0, "updated": 0}
whale_alerted = {}  # mint -> set of tx signatures already alerted

MC_MIN_USD = 3_000
MC_MAX_USD = 200_000
WHALE_MIN_SOL = 2.0  # alert if single buy >= this

def get_sol_price():
    now = time.time()
    if now - sol_price_usd["updated"] < 60:
        return sol_price_usd["price"]
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd", timeout=5)
        price = r.json()["solana"]["usd"]
        sol_price_usd["price"] = price
        sol_price_usd["updated"] = now
        return price
    except:
        return sol_price_usd["price"]

def fmt_usd(sol_amount):
    try:
        price = get_sol_price()
        usd = sol_amount * price
        if usd >= 1_000_000:
            return "$"+str(round(usd/1_000_000, 2))+"M"
        elif usd >= 1_000:
            return "$"+str(round(usd/1_000, 1))+"K"
        else:
            return "$"+str(round(usd, 0))
    except:
        return "?"

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
    deadline = time.time() + 1800
    whale_alerted[mint] = set()

    def on_msg(ws, message):
        try:
            data = json.loads(message)
            mcap = data.get("marketCapSol", 0)
            tx_type = data.get("txType", "")
            sig = data.get("signature", "")

            # Whale buy detection
            if tx_type == "buy":
                sol_amt = data.get("solAmount", 0)
                if isinstance(sol_amt, (int, float)):
                    sol = sol_amt / 1e9 if sol_amt > 1000 else sol_amt
                    if sol >= WHALE_MIN_SOL and sig not in whale_alerted.get(mint, set()):
                        whale_alerted[mint].add(sig)
                        wallet = data.get("traderPublicKey", "???")
                        wallet_short = wallet[:6]+"..."+wallet[-4:] if len(wallet) > 10 else wallet
                        current_mcap = fmt_usd(mcap) if mcap else "?"
                        send_tele("🐋 <b>WHALE BUY DETECTED!</b>\n"
                                  "Token: <b>"+name+"</b> ($"+symbol+")\n"
                                  "━━━━━━━━━━━━━━\n"
                                  "💰 Buy: <b>"+str(round(sol, 2))+" SOL</b> ("+fmt_usd(sol)+")\n"
                                  "📊 MC Sekarang: "+current_mcap+"\n"
                                  "👛 Wallet: "+wallet_short+"\n"
                                  "🔗 pump.fun/"+mint)

            # TP/SL monitoring
            if mcap <= 0:
                return
            if mcap >= initial_mcap * 2:
                stats["win"] += 1
                send_tele("✅ <b>PUMP! 2x HIT!</b>\n"
                          "Token: <b>"+name+"</b> ($"+symbol+")\n"
                          "MC Awal: "+fmt_usd(initial_mcap)+"\n"
                          "MC Sekarang: "+fmt_usd(mcap)+"\n\n"
                          "📊 Win Rate: "+get_winrate())
                ws.close()
            elif mcap <= initial_mcap * 0.5:
                stats["loss"] += 1
                send_tele("❌ <b>DUMP! -50% HIT!</b>\n"
                          "Token: <b>"+name+"</b> ($"+symbol+")\n"
                          "MC Awal: "+fmt_usd(initial_mcap)+"\n"
                          "MC Sekarang: "+fmt_usd(mcap)+"\n\n"
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

        sol_p = get_sol_price()
        mcap_usd_val = initial_mcap * sol_p
        if mcap_usd_val < MC_MIN_USD or mcap_usd_val > MC_MAX_USD:
            return

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
        mcap_usd = fmt_usd(initial_mcap)
        mcap_sol = str(round(initial_mcap, 2)) if initial_mcap else "?"

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
               "📊 Market Cap: <b>"+mcap_usd+"</b> ("+mcap_sol+" SOL)\n"
               "🔗 pump.fun/"+mint+"\n"
               "━━━━━━━━━━━━━━\n"
               "📈 Win Rate: "+get_winrate()+"\n"
               "🐋 Whale alert aktif (≥"+str(WHALE_MIN_SOL)+" SOL)\n"
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
    send_tele("🟢 <b>PumpFun Scanner AKTIF!</b>\n"
              "Filter MC: <b>$3K - $200K</b>\n"
              "🐋 Whale alert: buy ≥ 2 SOL\n"
              "✅ Win/Loss tracking (TP: 2x | SL: -50%)")

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
    return "PumpFun Scanner | MC: $3K-$200K | Signals: "+str(total)+" | Win Rate: "+wr, 200
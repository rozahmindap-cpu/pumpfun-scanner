from flask import Flask
import requests, threading, time, json
import websocket

app = Flask(__name__)

BOT_TOKEN = "8546209847:AAFb6fa0yJBa5iQNWvE32p-rA8nwcrFlGfY"
CHAT_ID = "1603606771"
WS_URL = "wss://pumpportal.fun/api/data"
SOLANA_RPC = "https://api.mainnet-beta.solana.com"

stats = {"win": 0, "loss": 0}
sol_price_usd = {"price": 85.0, "updated": 0}

MC_ALERT_USD = 5_000
MC_MAX_USD = 200_000
WHALE_MIN_SOL = 2.0
WHALE_MAX_ALERTS = 3
MONITOR_WAIT_MIN = 30

def get_sol_price():
    now = time.time()
    if now - sol_price_usd["updated"] < 30:
        return sol_price_usd["price"]
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=SOLUSDT", timeout=5)
        price = float(r.json()["price"])
        sol_price_usd["price"] = price
        sol_price_usd["updated"] = now
        return price
    except:
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
            return "$" + str(round(usd / 1_000_000, 2)) + "M"
        elif usd >= 1_000:
            return "$" + str(round(usd / 1_000, 1)) + "K"
        else:
            return "$" + str(round(usd, 0))
    except:
        return "?"

def send_tele(msg):
    try:
        requests.post(
            "https://api.telegram.org/bot" + BOT_TOKEN + "/sendMessage",
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
    return str(pct) + "% (" + str(stats["win"]) + "W/" + str(stats["loss"]) + "L)"

def fetch_metadata(uri):
    try:
        if not uri:
            return {}
        r = requests.get(uri, timeout=5)
        return r.json()
    except:
        return {}

def fetch_coin_data(mint):
    try:
        r = requests.get("https://frontend-api.pump.fun/coins/" + mint, timeout=5)
        return r.json()
    except:
        return {}

def get_top_holder_pct(mint):
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenLargestAccounts",
            "params": [mint]
        }
        r = requests.post(SOLANA_RPC, json=payload, timeout=8)
        result = r.json().get("result", {}).get("value", [])
        if not result:
            return None, None
        amounts = [float(x.get("uiAmount", 0)) for x in result]
        total = sum(amounts)
        if total == 0:
            return None, None
        top1_pct = round(amounts[0] / total * 100, 1)
        top5_pct = round(sum(amounts[:5]) / total * 100, 1)
        return top1_pct, top5_pct
    except:
        return None, None

token_count = {"n": 0}

def watch_token(data):
    try:
        name = data.get("name", "Unknown")
        symbol = data.get("symbol", "???")
        mint = data.get("mint", "")
        uri = data.get("uri", "")

        sol_p = get_sol_price()
        mc_alert_sol = MC_ALERT_USD / sol_p
        mc_max_sol = MC_MAX_USD / sol_p

        state = {"alerted": False, "entry_mcap": 0, "whale_count": 0}
        deadline = time.time() + (MONITOR_WAIT_MIN * 60)

        def on_msg(ws, message):
            try:
                d = json.loads(message)
                mcap = d.get("marketCapSol", 0)
                tx_type = d.get("txType", "")
                sig = d.get("signature", "")

                if mcap <= 0:
                    return
                if mcap > mc_max_sol:
                    ws.close()
                    return
                if time.time() > deadline and not state["alerted"]:
                    ws.close()
                    return

                # First alert when MC hits threshold
                if not state["alerted"] and mcap >= mc_alert_sol:
                    state["alerted"] = True
                    state["entry_mcap"] = mcap

                    meta = fetch_metadata(uri)
                    coin = fetch_coin_data(mint)
                    top1_pct, top5_pct = get_top_holder_pct(mint)

                    twitter = meta.get("twitter") or coin.get("twitter") or ""
                    telegram_link = meta.get("telegram") or coin.get("telegram") or ""
                    website = meta.get("website") or coin.get("website") or ""
                    description = meta.get("description") or coin.get("description") or ""
                    holder_count = coin.get("holder_count") or "?"

                    rug_score = 0
                    if not twitter: rug_score += 15
                    if not telegram_link: rug_score += 10
                    if not website: rug_score += 5
                    if not description or len(description) < 10: rug_score += 10
                    if top1_pct and top1_pct > 50: rug_score += 30
                    elif top1_pct and top1_pct > 30: rug_score += 15
                    elif top1_pct and top1_pct > 20: rug_score += 8
                    rug_score = min(rug_score, 100)
                    safe_score = 100 - rug_score

                    if safe_score >= 70:
                        risk_label = "LOW RISK"
                        risk_icon = "[HIJAU]"
                    elif safe_score >= 50:
                        risk_label = "MEDIUM RISK"
                        risk_icon = "[KUNING]"
                    else:
                        risk_label = "HIGH RISK"
                        risk_icon = "[MERAH]"

                    tw = "YES" if twitter else "NO"
                    tg = "YES" if telegram_link else "NO"
                    wb = "YES" if website else "NO"
                    desc_short = description[:80] + "..." if len(description) > 80 else (description or "-")
                    top1_str = str(top1_pct) + "%" if top1_pct else "?"
                    top5_str = str(top5_pct) + "%" if top5_pct else "?"
                    top1_warn = " WARN" if top1_pct and top1_pct > 20 else " OK"
                    top5_warn = " WARN" if top5_pct and top5_pct > 50 else " OK"

                    send_tele(
                        "&#128640; <b>TOKEN AKTIF!</b>\n"
                        "&#9473;&#9473;&#9473;&#9473;&#9473;&#9473;&#9473;\n"
                        "&#128204; <b>" + name + "</b> ($" + symbol + ")\n"
                        "&#9473;&#9473;&#9473;&#9473;&#9473;&#9473;&#9473;\n"
                        + risk_icon + " <b>Safe Score: " + str(safe_score) + "/100</b> - " + risk_label + "\n"
                        "&#9473;&#9473;&#9473;&#9473;&#9473;&#9473;&#9473;\n"
                        "Twitter: " + tw + " | Telegram: " + tg + " | Web: " + wb + "\n"
                        "Desc: " + desc_short + "\n"
                        "&#9473;&#9473;&#9473;&#9473;&#9473;&#9473;&#9473;\n"
                        "Holders: <b>" + str(holder_count) + "</b>\n"
                        "Top 1 holder: <b>" + top1_str + "</b>" + top1_warn + "\n"
                        "Top 5 holders: <b>" + top5_str + "</b>" + top5_warn + "\n"
                        "&#9473;&#9473;&#9473;&#9473;&#9473;&#9473;&#9473;\n"
                        "Market Cap: <b>" + fmt_usd(mcap) + "</b>\n"
                        "&#128279; pump.fun/" + mint + "\n"
                        "&#9473;&#9473;&#9473;&#9473;&#9473;&#9473;&#9473;\n"
                        "Win Rate: " + get_winrate() + "\n"
                        "Monitoring TP 2x / SL -50%..."
                    )

                # Whale alert (max 3 per token)
                if state["alerted"] and tx_type == "buy" and state["whale_count"] < WHALE_MAX_ALERTS:
                    sol_amt = d.get("solAmount", 0)
                    if isinstance(sol_amt, (int, float)):
                        sol = sol_amt / 1e9 if sol_amt > 1000 else sol_amt
                        if sol >= WHALE_MIN_SOL:
                            state["whale_count"] += 1
                            wallet = d.get("traderPublicKey", "???")
                            wallet_short = wallet[:6] + "..." + wallet[-4:] if len(wallet) > 10 else wallet
                            send_tele(
                                "&#128011; <b>WHALE BUY!</b>\n"
                                "Token: <b>" + name + "</b> ($" + symbol + ")\n"
                                "Buy: <b>" + str(round(sol, 2)) + " SOL</b> (" + fmt_usd(sol) + ")\n"
                                "MC: " + fmt_usd(mcap) + "\n"
                                "Wallet: " + wallet_short + "\n"
                                "&#128279; pump.fun/" + mint
                            )

                # TP/SL
                if state["alerted"]:
                    entry = state["entry_mcap"]
                    if mcap >= entry * 2:
                        stats["win"] += 1
                        send_tele(
                            "&#9989; <b>PUMP! 2x HIT!</b>\n"
                            "Token: <b>" + name + "</b> ($" + symbol + ")\n"
                            "MC: " + fmt_usd(entry) + " → " + fmt_usd(mcap) + "\n\n"
                            "Win Rate: " + get_winrate()
                        )
                        ws.close()
                    elif mcap <= entry * 0.5:
                        stats["loss"] += 1
                        send_tele(
                            "&#10060; <b>DUMP! -50% HIT!</b>\n"
                            "Token: <b>" + name + "</b> ($" + symbol + ")\n"
                            "MC: " + fmt_usd(entry) + " → " + fmt_usd(mcap) + "\n\n"
                            "Win Rate: " + get_winrate()
                        )
                        ws.close()
            except:
                pass

        def on_open_w(ws):
            print("Monitoring: " + name + " ($" + symbol + ") mint=" + mint[:8])
            ws.send(json.dumps({"method": "subscribeTokenTrade", "keys": [mint]}))

        def run():
            try:
                ws = websocket.WebSocketApp(WS_URL, on_message=on_msg, on_open=on_open_w)
                ws.run_forever()
            except:
                pass

        threading.Thread(target=run, daemon=True).start()

    except Exception as e:
        print("watch error:", str(e))

def on_message(ws, message):
    try:
        data = json.loads(message)
        if data.get("txType") == "create":
            token_count["n"] += 1
            threading.Thread(target=watch_token, args=(data,), daemon=True).start()
    except Exception as e:
        print("on_message error:", str(e))

def on_open(ws):
    print("WS connected")
    ws.send(json.dumps({"method": "subscribeNewToken"}))
    send_tele(
        "&#128994; <b>PumpFun Scanner AKTIF!</b>\n"
        "Alert MC: <b>$5K+</b> | Max: <b>$200K</b>\n"
        "Holders + Top holder % aktif\n"
        "Whale alert &gt;= 2 SOL (max 3x per token)\n"
        "TP: 2x | SL: -50%"
    )

def on_error(ws, error):
    print("WS error:", str(error))

def on_close(ws, *args):
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
    return "PumpFun Scanner | Alert $5K+ | Tokens seen: " + str(token_count["n"]) + " | Win Rate: " + wr, 200

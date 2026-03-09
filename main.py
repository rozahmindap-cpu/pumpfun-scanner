from flask import Flask
import requests, threading, time, json
import websocket

app = Flask(__name__)

BOT_TOKEN = "8546209847:AAFb6fa0yJBa5iQNWvE32p-rA8nwcrFlGfY"
CHAT_ID = "1603606771"
WS_URL = "wss://pumpportal.fun/api/data"
SOLANA_RPC = "https://api.mainnet-beta.solana.com"

stats = {"win": 0, "loss": 0}
sol_price_usd = {"price": 130.0, "updated": 0}

MC_ALERT_USD = 10_000
MC_MAX_USD = 200_000
WHALE_MIN_SOL = 2.0
MONITOR_WAIT_MIN = 10

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

def fetch_coin_data(mint):
    try:
        r = requests.get("https://frontend-api.pump.fun/coins/"+mint, timeout=5)
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

def watch_token(data):
    try:
        name = data.get("name", "Unknown")
        symbol = data.get("symbol", "???")
        mint = data.get("mint", "")
        uri = data.get("uri", "")

        sol_p = get_sol_price()
        mc_alert_sol = MC_ALERT_USD / sol_p
        mc_max_sol = MC_MAX_USD / sol_p

        alerted = {"sent": False}
        whale_sigs = set()
        deadline = time.time() + (MONITOR_WAIT_MIN * 60)

        def on_msg(ws, message):
            try:
                data_trade = json.loads(message)
                mcap = data_trade.get("marketCapSol", 0)
                tx_type = data_trade.get("txType", "")
                sig = data_trade.get("signature", "")

                if mcap <= 0:
                    return
                if mcap > mc_max_sol:
                    ws.close()
                    return
                if time.time() > deadline and not alerted["sent"]:
                    ws.close()
                    return

                if not alerted["sent"] and mcap >= mc_alert_sol:
                    alerted["sent"] = True
                    alerted["entry_mcap"] = mcap

                    meta = fetch_metadata(uri)
                    coin = fetch_coin_data(mint)
                    top1_pct, top5_pct = get_top_holder_pct(mint)

                    twitter = meta.get("twitter") or coin.get("twitter") or ""
                    telegram = meta.get("telegram") or coin.get("telegram") or ""
                    website = meta.get("website") or coin.get("website") or ""
                    description = meta.get("description") or coin.get("description") or ""
                    holder_count = coin.get("holder_count") or coin.get("holders") or "?"

                    rug_score = 0
                    if not twitter: rug_score += 15
                    if not telegram: rug_score += 10
                    if not website: rug_score += 5
                    if not description or len(description) < 10: rug_score += 10
                    if top1_pct and top1_pct > 50: rug_score += 30
                    elif top1_pct and top1_pct > 30: rug_score += 15
                    elif top1_pct and top1_pct > 20: rug_score += 8
                    rug_score = min(rug_score, 100)
                    safe_score = 100 - rug_score

                    if safe_score >= 70:
                        risk_emoji = "ðŸŸ¢"
                        risk_label = "LOW RISK"
                    elif safe_score >= 50:
                        risk_emoji = "ðŸŸ¡"
                        risk_label = "MEDIUM RISK"
                    else:
                        risk_emoji = "ðŸ”´"
                        risk_label = "HIGH RISK"

                    has_twitter = "âœ…" if twitter else "âŒ"
                    has_telegram = "âœ…" if telegram else "âŒ"
                    has_website = "âœ…" if website else "âŒ"
                    desc_short = description[:80]+"..." if len(description) > 80 else (description or "-")

                    top1_str = str(top1_pct)+"%" if top1_pct else "?"
                    top5_str = str(top5_pct)+"%" if top5_pct else "?"
                    top1_warn = " âš ï¸" if top1_pct and top1_pct > 20 else " âœ…"
                    top5_warn = " âš ï¸" if top5_pct and top5_pct > 50 else " âœ…"

                    send_tele("ðŸš€ <b>TOKEN AKTIF!</b>\n"
                              "â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
                              "ðŸ“Œ <b>"+name+"</b> ($"+symbol+")\n"
                              "â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
                              +risk_emoji+" <b>Safe Score: "+str(safe_score)+"/100</b> â€” "+risk_label+"\n"
                              "â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
                              "ðŸ¦ Twitter: "+has_twitter+" | ðŸ’¬ TG: "+has_telegram+" | ðŸŒ Web: "+has_website+"\n"
                              "ðŸ“ "+desc_short+"\n"
                              "â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
                              "ðŸ‘¥ Holders: <b>"+str(holder_count)+"</b>\n"
                              "ðŸ† Top 1 holder: <b>"+top1_str+"</b>"+top1_warn+"\n"
                              "ðŸ… Top 5 holders: <b>"+top5_str+"</b>"+top5_warn+"\n"
                              "â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
                              "ðŸ“Š Market Cap: <b>"+fmt_usd(mcap)+"</b>\n"
                              "ðŸ”— pump.fun/"+mint+"\n"
                              "â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
                              "ðŸ“ˆ Win Rate: "+get_winrate()+"\n"
                              "ðŸ‹ Whale alert aktif (>="+str(WHALE_MIN_SOL)+" SOL)")

                if alerted["sent"] and tx_type == "buy" and sig not in whale_sigs:
                    sol_amt = data_trade.get("solAmount", 0)
                    if isinstance(sol_amt, (int, float)):
                        sol = sol_amt / 1e9 if sol_amt > 1000 else sol_amt
                        if sol >= WHALE_MIN_SOL:
                            whale_sigs.add(sig)
                            wallet = data_trade.get("traderPublicKey", "???")
                            wallet_short = wallet[:6]+"..."+wallet[-4:] if len(wallet) > 10 else wallet
                            send_tele("ðŸ‹ <b>WHALE BUY!</b>\n"
                                      "Token: <b>"+name+"</b> ($"+symbol+")\n"
                                      "ðŸ’° Buy: <b>"+str(round(sol, 2))+" SOL</b> ("+fmt_usd(sol)+")\n"
                                      "ðŸ“Š MC: "+fmt_usd(mcap)+"\n"
                                      "ðŸ‘› "+wallet_short+"\n"
                                      "ðŸ”— pump.fun/"+mint)

                if alerted["sent"]:
                    entry = alerted.get("entry_mcap", mcap)
                    if mcap >= entry * 2:
                        stats["win"] += 1
                        send_tele("âœ… <b>PUMP! 2x HIT!</b>\n"
                                  "Token: <b>"+name+"</b> ($"+symbol+")\n"
                                  "MC Entry: "+fmt_usd(entry)+" -> "+fmt_usd(mcap)+"\n\n"
                                  "ðŸ“Š Win Rate: "+get_winrate())
                        ws.close()
                    elif mcap <= entry * 0.5:
                        stats["loss"] += 1
                        send_tele("âŒ <b>DUMP! -50% HIT!</b>\n"
                                  "Token: <b>"+name+"</b> ($"+symbol+")\n"
                                  "MC Entry: "+fmt_usd(entry)+" -> "+fmt_usd(mcap)+"\n\n"
                                  "ðŸ“Š Win Rate: "+get_winrate())
                        ws.close()
            except:
                pass

        def on_open_w(ws):
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

token_count = {"n": 0}

def on_message(ws, message):
    try:
        data = json.loads(message)
        if data.get("txType") == "create":
            token_count["n"] += 1
            mcap = data.get("marketCapSol", 0)
            sol_p = get_sol_price()
            mcap_usd = mcap * sol_p
            # Debug: log first 3 tokens received
            if token_count["n"] <= 3:
                send_tele("🔍 <b>Debug Token #"+str(token_count["n"])+"</b>\n"
                          "Name: "+str(data.get("name","?"))+"\n"
                          "MC: "+fmt_usd(mcap)+" ("+str(round(mcap,2))+" SOL)\n"
                          "Mint: "+str(data.get("mint","?"))[:20]+"...")
            threading.Thread(target=watch_token, args=(data,), daemon=True).start()
    except Exception as e:
        print("on_message error:", str(e))

def on_open(ws):
    print("WS connected")
    ws.send(json.dumps({"method": "subscribeNewToken"}))
    send_tele("ðŸŸ¢ <b>PumpFun Scanner AKTIF!</b>\n"
              "Alert saat MC: <b>$10K+</b> | Max: <b>$200K</b>\n"
              "ðŸ‘¥ Holder count + top holder % aktif\n"
              "ðŸ‹ Whale alert >= 2 SOL | TP: 2x | SL: -50%")

def on_error(ws, error):
    print("WS error:", str(error))

def on_close(ws, *args):
    print("WS closed, reconnecting...")

def run_scanner():
    while True:
        try:
            ws = websocket.WebSocketApp(WS_URL, on_message=on_message, on_open=on_open, on_error=on_error, on_close=on_close)
            ws.run_forever(ping_interval=30, ping_timeout=10)
        except Exception as e:
            print("Scanner error:", str(e))
        time.sleep(5)

threading.Thread(target=run_scanner, daemon=True).start()

@app.route("/")
def home():
    wr = get_winrate()
    total = stats["win"] + stats["loss"]
    return "PumpFun Scanner | Alert $10K+ | Signals: "+str(total)+" | Win Rate: "+wr, 200

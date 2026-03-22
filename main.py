import os
import requests
from flask import Flask, request
from datetime import datetime, timedelta
import threading
import schedule
import time

app = Flask(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
BIG_SALE_THRESHOLD = float(os.environ.get("BIG_SALE_THRESHOLD", 500))
CASPIT_BASE = "https://caspitlight.valu.co.il"

daily_sales = {"total": 0, "count": 0}
last_seen_id = None
access_token = None

DAY_NAMES = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

def format_date(dt, end_of_day=False):
    if end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59)
    else:
        dt = dt.replace(hour=0, minute=0, second=0)
    day = DAY_NAMES[dt.weekday()]
    month = MONTH_NAMES[dt.month - 1]
    t = dt.strftime("%H:%M:%S")
    return f"{day}+{month}+{dt.day:02d}+{dt.year}+{t}+GMT%2B0200+(Israel+Standard+Time)"

def get_headers():
    return {"Authorization": f"Token {access_token}", "Content-Type": "application/json"}

def fetch_sales(from_dt, to_dt):
    from_str = format_date(from_dt, end_of_day=False)
    to_str = format_date(to_dt, end_of_day=True)
    url = f"{CASPIT_BASE}/bo/sales?page=1&per=500&by_from_date={from_str}&by_to_date={to_str}&by_is_by_hour=false&by_from_minute=00&by_from_hour=00&by_to_minute=59&by_to_hour=23"
    print(f"Fetching: {url[:100]}")
    r = requests.get(url, headers=get_headers(), timeout=10)
    print(f"Status: {r.status_code}")
    return r

def is_active_hours():
    now = datetime.now()
    weekday = now.weekday()
    hour = now.hour
    if weekday == 5:
        return False
    elif weekday == 4:
        return 10 <= hour < 16
    else:
        return 10 <= hour < 20

def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"})

def check_new_sales():
    global last_seen_id
    if not access_token or not is_active_hours():
        return
    try:
        now = datetime.now()
        r = fetch_sales(now, now)
        if r.status_code != 200:
            return
        data = r.json()
        sales = data.get("sales", data) if isinstance(data, dict) else data
        if not sales:
            return
        latest_id = sales[0].get("id")
        if last_seen_id is None:
            last_seen_id = latest_id
            return
        new_sales = []
        for sale in sales:
            if sale.get("id") == last_seen_id:
                break
            new_sales.append(sale)
        for sale in reversed(new_sales):
            amount = float(sale.get("amount", 0))
            invoice = sale.get("invoice_number", "")
            sold_at = sale.get("sold_at", "")[:16] if sale.get("sold_at") else ""
            daily_sales["total"] += amount
            daily_sales["count"] += 1
            send_telegram(
                f"🛒 <b>מכירה חדשה!</b>\n"
                f"💰 סכום: ₪{amount:.2f}\n"
                f"🧾 חשבונית: {invoice}\n"
                f"🕐 שעה: {sold_at}"
            )
            if amount >= BIG_SALE_THRESHOLD:
                send_telegram(f"🚀 <b>מכירה גדולה!</b> ₪{amount:.2f} 🎉")
        if new_sales:
            last_seen_id = new_sales[0].get("id")
    except Exception as e:
        print(f"Error: {e}")

def send_daily_summary():
    total = daily_sales["total"]
    count = daily_sales["count"]
    avg = total / count if count > 0 else 0
    send_telegram(
        f"📊 <b>סיכום יומי</b>\n"
        f"💰 סה\"כ: ₪{total:.2f}\n"
        f"🧾 עסקאות: {count}\n"
        f"📈 ממוצע: ₪{avg:.2f}\n"
        f"🌿 לילה טוב!"
    )
    daily_sales["total"] = 0
    daily_sales["count"] = 0

@app.route("/token", methods=["POST"])
def receive_token():
    global access_token, last_seen_id
    data = request.json or {}
    new_token = data.get("token")
    if new_token:
        access_token = new_token
        last_seen_id = data.get("last_id", last_seen_id)
        print(f"Token updated!")
        send_telegram("✅ <b>SellsFlow מעודכן!</b>\nהטוקן קובל מהדפדפן 🌿")
    return {"status": "ok"}, 200

@app.route("/webhook", methods=["POST"])
def webhook():
    return {"status": "ok"}, 200

@app.route("/", methods=["GET"])
def home():
    return {"status": "SellsFlow active", "has_token": access_token is not None}, 200

def run_scheduler():
    schedule.every(2).minutes.do(check_new_sales)
    schedule.every().monday.at("20:00").do(send_daily_summary)
    schedule.every().tuesday.at("20:00").do(send_daily_summary)
    schedule.every().wednesday.at("20:00").do(send_daily_summary)
    schedule.every().thursday.at("20:00").do(send_daily_summary)
    schedule.every().sunday.at("20:00").do(send_daily_summary)
    schedule.every().friday.at("16:00").do(send_daily_summary)
    while True:
        schedule.run_pending()
        time.sleep(30)

threading.Thread(target=run_scheduler, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print("SellsFlow Bot started - waiting for token...")
    app.run(host="0.0.0.0", port=port)

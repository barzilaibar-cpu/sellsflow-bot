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

daily_sales = {"total": 0, "count": 0}
last_seen_id = None

DAY_NAMES = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

def get_headers():
    cookie = os.environ.get("CASPIT_COOKIE", "")
    return {"Cookie": cookie}

def format_caspit_date(dt, end_of_day=False):
    if end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59)
    else:
        dt = dt.replace(hour=0, minute=0, second=0)
    day = DAY_NAMES[dt.weekday()]
    month = MONTH_NAMES[dt.month - 1]
    time_str = dt.strftime("%H:%M:%S")
    return f"{day}+{month}+{dt.day:02d}+{dt.year}+{time_str}+GMT%2B0200+(Israel+Standard+Time)"

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

def send_telegram(message, reply_markup=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    requests.post(url, json=payload)

def get_sales_for_period(days_ago_start, days_ago_end=0):
    try:
        from_dt = datetime.now() - timedelta(days=days_ago_start)
        to_dt = datetime.now() - timedelta(days=days_ago_end)
        from_str = format_caspit_date(from_dt, end_of_day=False)
        to_str = format_caspit_date(to_dt, end_of_day=True)
        url = f"https://caspitlight.valu.co.il/bo/sales?page=1&per=500&by_from_date={from_str}&by_to_date={to_str}&by_is_by_hour=false&by_from_minute=00&by_from_hour=00&by_to_minute=59&by_to_hour=23"
        print(f"Fetching: {url[:120]}")
        response = requests.get(url, headers=get_headers(), timeout=10)
        print(f"Status: {response.status_code}, Length: {len(response.text)}")
        data = response.json()
        sales = data.get("sales", data) if isinstance(data, dict) else data
        total = sum(float(s.get("amount", 0)) for s in (sales or []))
        count = len(sales or [])
        print(f"Found {count} sales, total {total}")
        return total, count
    except Exception as e:
        print(f"Error getting sales: {e}")
        return 0, 0

def check_new_sales():
    global last_seen_id
    if not is_active_hours():
        return
    try:
        from_str = format_caspit_date(datetime.now(), end_of_day=False)
        to_str = format_caspit_date(datetime.now(), end_of_day=True)
        url = f"https://caspitlight.valu.co.il/bo/sales?page=1&per=25&by_from_date={from_str}&by_to_date={to_str}&by_is_by_hour=false&by_from_minute=00&by_from_hour=00&by_to_minute=59&by_to_hour=23"
        response = requests.get(url, headers=get_headers(), timeout=10)
        data = response.json()
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
            msg = (
                f"🛒 <b>מכירה חדשה!</b>\n"
                f"💰 סכום: ₪{amount:.2f}\n"
                f"🧾 חשבונית: {invoice}\n"
                f"🕐 שעה: {sold_at}"
            )
            send_telegram(msg)
            if amount >= BIG_SALE_THRESHOLD:
                send_telegram(f"🚀 <b>מכירה גדולה!</b> ₪{amount:.2f} 🎉")
        if new_sales:
            last_seen_id = new_sales[0].get("id")
    except Exception as e:
        print(f"Error checking sales: {e}")

def send_summary(label="סיכום"):
    total_today, count_today = get_sales_for_period(0, 0)
    total_week_ago, _ = get_sales_for_period(7, 7)
    avg = total_today / count_today if count_today > 0 else 0
    diff = total_today - total_week_ago
    arrow = "↑" if diff >= 0 else "↓"
    pct = abs(diff / total_week_ago * 100) if total_week_ago > 0 else 0
    keyboard = {"inline_keyboard": [[
        {"text": "📊 היום", "callback_data": "today"},
        {"text": "📅 השבוע", "callback_data": "week"},
        {"text": "🗓 החודש", "callback_data": "month"}
    ]]}
    msg = (
        f"📊 <b>{label}</b>\n"
        f"💰 סה\"כ היום: ₪{total_today:.2f}\n"
        f"🧾 עסקאות: {count_today}\n"
        f"📈 ממוצע: ₪{avg:.2f}\n"
        f"📅 לפני שבוע: ₪{total_week_ago:.2f} {arrow}{pct:.0f}%"
    )
    send_telegram(msg, reply_markup=keyboard)

@app.route("/webhook", methods=["POST", "OPTIONS"])
def webhook():
    data = request.json or {}
    if "callback_query" in data:
        cb = data["callback_query"]
        action = cb.get("data")
        if action == "today":
            total, count = get_sales_for_period(0, 0)
            send_telegram(f"📊 <b>היום</b>\n💰 ₪{total:.2f} | {count} עסקאות")
        elif action == "week":
            total, count = get_sales_for_period(6, 0)
            send_telegram(f"📅 <b>השבוע</b>\n💰 ₪{total:.2f} | {count} עסקאות")
        elif action == "month":
            total, count = get_sales_for_period(29, 0)
            send_telegram(f"🗓 <b>החודש</b>\n💰 ₪{total:.2f} | {count} עסקאות")
    return {"status": "ok"}, 200

@app.route("/", methods=["GET"])
def home():
    return {"status": "SellsFlow Bot פעיל ✅"}, 200

def run_scheduler():
    schedule.every(2).minutes.do(check_new_sales)
    schedule.every().day.at("14:00").do(lambda: send_summary("סיכום חצי יום"))
    schedule.every().monday.at("20:00").do(lambda: send_summary("סיכום יומי"))
    schedule.every().tuesday.at("20:00").do(lambda: send_summary("סיכום יומי"))
    schedule.every().wednesday.at("20:00").do(lambda: send_summary("סיכום יומי"))
    schedule.every().thursday.at("20:00").do(lambda: send_summary("סיכום יומי"))
    schedule.every().sunday.at("20:00").do(lambda: send_summary("סיכום יומי"))
    schedule.every().friday.at("16:00").do(lambda: send_summary("סיכום שישי"))
    while True:
        schedule.run_pending()
        time.sleep(30)

threading.Thread(target=run_scheduler, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    send_telegram("✅ <b>SellsFlow Bot הופעל!</b> 🌿")
    app.run(host="0.0.0.0", port=port)

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
CASPIT_COOKIE = os.environ.get("CASPIT_COOKIE")

daily_sales = {"total": 0, "count": 0}
last_seen_id = None

CASPIT_HEADERS = {"Cookie": CASPIT_COOKIE} if CASPIT_COOKIE else {}

def is_active_hours():
    now = datetime.now()
    weekday = now.weekday()  # 0=Monday, 6=Sunday
    hour = now.hour
    # ראשון = 6, שני-חמישי = 0-3, שישי = 4
    if weekday == 5:  # שבת
        return False
    elif weekday == 4:  # שישי
        return 10 <= hour < 16
    else:  # ראשון-חמישי
        return 10 <= hour < 20

def send_telegram(message, reply_markup=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    requests.post(url, json=payload)

def get_sales_for_period(days_ago_start, days_ago_end=0):
    try:
        from urllib.parse import quote
        def format_date(days_ago, end_of_day=False):
            d = datetime.now() - timedelta(days=days_ago)
            if end_of_day:
                d = d.replace(hour=23, minute=59, second=59)
            else:
                d = d.replace(hour=0, minute=0, second=0)
            # Format like Keshafit expects
            day_names = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
            month_names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
            day_name = day_names[d.weekday()]
            month_name = month_names[d.month - 1]
            return quote(f"{day_name}+{month_name}+{d.day:02d}+{d.year}+{d.hour:02d}:{d.minute:02d}:{d.second:02d}+GMT+0200+(Israel+Standard+Time)")

        from_str = format_date(days_ago_start)
        to_str = format_date(days_ago_end, end_of_day=True)
        url = f"https://caspitlight.valu.co.il/bo/sales?page=1&per=500&by_from_date={from_str}&by_to_date={to_str}"
        response = requests.get(url, headers=CASPIT_HEADERS, timeout=10)
        data = response.json()
        sales = data.get("sales", data) if isinstance(data, dict) else data
        total = sum(float(s.get("amount", 0)) for s in sales)
        count = len(sales)
        return total, count
    except Exception as e:
        print(f"Error getting sales: {e}")
        return 0, 0

def get_date_str(days_ago=0):
    d = datetime.now() - timedelta(days=days_ago)
    return d.strftime("%d/%m/%Y")

def check_new_sales():
    global last_seen_id
    if not is_active_hours():
        return
    try:
        today = get_date_str()
        url = f"https://caspitlight.valu.co.il/bo/sales?page=1&per=25&by_from_date={today}&by_to_date={today}"
        response = requests.get(url, headers=CASPIT_HEADERS, timeout=10)
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
        print(f"Error: {e}")

def send_summary(label="סיכום"):
    today = get_date_str()
    last_week = get_date_str(7)
    total_today, count_today = get_sales_for_period(today, today)
    total_week_ago, _ = get_sales_for_period(last_week, last_week)
    avg = total_today / count_today if count_today > 0 else 0
    diff = total_today - total_week_ago
    arrow = "↑" if diff >= 0 else "↓"
    pct = abs(diff / total_week_ago * 100) if total_week_ago > 0 else 0
    msg = (
        f"📊 <b>{label}</b>\n"
        f"💰 סה\"כ היום: ₪{total_today:.2f}\n"
        f"🧾 עסקאות: {count_today}\n"
        f"📈 ממוצע: ₪{avg:.2f}\n"
        f"📅 לפני שבוע: ₪{total_week_ago:.2f} {arrow}{pct:.0f}%"
    )
    keyboard = {
        "inline_keyboard": [[
            {"text": "📊 היום", "callback_data": "today"},
            {"text": "📅 השבוע", "callback_data": "week"},
            {"text": "🗓 החודש", "callback_data": "month"}
        ]]
    }
    send_telegram(msg, reply_markup=keyboard)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json or {}
    if "callback_query" in data:
        cb = data["callback_query"]
        action = cb.get("data")
        today = get_date_str()
        if action == "today":
            total, count = get_sales_for_period(today, today)
            send_telegram(f"📊 <b>היום</b>\n💰 ₪{total:.2f} | {count} עסקאות")
        elif action == "week":
            from_date = get_date_str(6)
            total, count = get_sales_for_period(from_date, today)
            send_telegram(f"📅 <b>השבוע</b>\n💰 ₪{total:.2f} | {count} עסקאות")
        elif action == "month":
            from_date = get_date_str(29)
            total, count = get_sales_for_period(from_date, today)
            send_telegram(f"🗓 <b>החודש</b>\n💰 ₪{total:.2f} | {count} עסקאות")
    return {"status": "ok"}, 200

@app.route("/", methods=["GET"])
def home():
    return {"status": "SellsFlow Bot פעיל ✅"}, 200

def run_scheduler():
    # בדיקת מכירות כל 2 דקות
    schedule.every(2).minutes.do(check_new_sales)
    # סיכום חצי יום ב-14:00
    schedule.every().day.at("14:00").do(lambda: send_summary("סיכום חצי יום"))
    # סיכום סוף יום — ראשון-חמישי ב-20:00
    schedule.every().monday.at("20:00").do(lambda: send_summary("סיכום יומי"))
    schedule.every().tuesday.at("20:00").do(lambda: send_summary("סיכום יומי"))
    schedule.every().wednesday.at("20:00").do(lambda: send_summary("סיכום יומי"))
    schedule.every().thursday.at("20:00").do(lambda: send_summary("סיכום יומי"))
    schedule.every().sunday.at("20:00").do(lambda: send_summary("סיכום יומי"))
    # סיכום שישי ב-16:00
    schedule.every().friday.at("16:00").do(lambda: send_summary("סיכום שישי"))
    while True:
        schedule.run_pending()
        time.sleep(30)

threading.Thread(target=run_scheduler, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    send_telegram("✅ <b>SellsFlow Bot הופעל!</b> 🌿")
    app.run(host="0.0.0.0", port=port)

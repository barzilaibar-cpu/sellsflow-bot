import os
import json
import requests
from flask import Flask, request
from datetime import datetime
import threading
import schedule
import time

app = Flask(__name__)

# משתני סביבה
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
BIG_SALE_THRESHOLD = float(os.environ.get("BIG_SALE_THRESHOLD", 500))

# מעקב מכירות יומי
daily_sales = {"total": 0, "count": 0}

def send_telegram(message):
    """שליחת הודעה לטלגרם"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"})

def format_items(items):
    """פורמט רשימת פריטים"""
    if not items:
        return "לא צוין"
    return "\n".join([f"  • {item.get('name', 'פריט')} - ₪{item.get('price', 0)}" for item in items])

@app.route("/webhook", methods=["POST"])
def webhook():
    """קבלת אירועים מכספית HYP"""
    data = request.json or {}
    event_type = data.get("event_type", "")
    
    now = datetime.now().strftime("%H:%M")
    
    # מכירה חדשה
    if event_type in ["sale", "payment", "transaction"]:
        amount = float(data.get("amount", 0))
        payment_method = data.get("payment_method", "לא צוין")
        items = data.get("items", [])
        
        daily_sales["total"] += amount
        daily_sales["count"] += 1
        
        items_text = format_items(items)
        
        msg = (
            f"🛒 <b>מכירה חדשה!</b>\n"
            f"💰 סכום: ₪{amount:.2f}\n"
            f"💳 תשלום: {payment_method}\n"
            f"🕐 שעה: {now}\n"
            f"📦 פריטים:\n{items_text}"
        )
        send_telegram(msg)
        
        # התראה על מכירה גדולה
        if amount >= BIG_SALE_THRESHOLD:
            send_telegram(f"🚀 <b>מכירה גדולה!</b> ₪{amount:.2f} - כל הכבוד! 🎉")
    
    # החזר / ביטול
    elif event_type in ["refund", "cancel", "void"]:
        amount = float(data.get("amount", 0))
        reason = data.get("reason", "לא צוין")
        msg = (
            f"⚠️ <b>החזר / ביטול</b>\n"
            f"💸 סכום: ₪{amount:.2f}\n"
            f"📝 סיבה: {reason}\n"
            f"🕐 שעה: {now}"
        )
        send_telegram(msg)
    
    return {"status": "ok"}, 200

def send_daily_summary():
    """סיכום יומי - נשלח ב-20:00"""
    total = daily_sales["total"]
    count = daily_sales["count"]
    avg = total / count if count > 0 else 0
    
    msg = (
        f"📊 <b>סיכום יומי</b>\n"
        f"💰 סה\"כ מכירות: ₪{total:.2f}\n"
        f"🧾 מספר עסקאות: {count}\n"
        f"📈 ממוצע לעסקה: ₪{avg:.2f}\n"
        f"🌿 לילה טוב!"
    )
    send_telegram(msg)
    
    # איפוס ליום הבא
    daily_sales["total"] = 0
    daily_sales["count"] = 0

def run_scheduler():
    schedule.every().day.at("20:00").do(send_daily_summary)
    while True:
        schedule.run_pending()
        time.sleep(60)

# הפעלת scheduler ברקע
threading.Thread(target=run_scheduler, daemon=True).start()

@app.route("/", methods=["GET"])
def home():
    return {"status": "SellsFlow Bot פעיל ✅"}, 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    send_telegram("✅ <b>SellsFlow Bot הופעל!</b>\nמוכן לקבל התראות מהקופה 🌿")
    app.run(host="0.0.0.0", port=port)

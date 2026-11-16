import requests
import time
from datetime import datetime

# ======================
# CONFIGURATION
# ======================
WEBHOOK_URL = "https://discord.com/api/webhooks/1571990911737405582/gk8RqKJdRWjOSahlwoJ1jwgLeGTycEsYipFkYJaidcvUb2mgtv8uGPjBNM888r49wfqp"
CHECK_INTERVAL = 120  # 2 minutes

def send_discord_message(content: str, title: str = "Memecoin Alert"):
    data = {
        "embeds": [{
            "title": title,
            "description": content,
            "color": 0x00ff99,
            "timestamp": datetime.utcnow().isoformat()
        }]
    }
    try:
        response = requests.post(WEBHOOK_URL, json=data)
        if response.status_code == 204:
            print("Message sent successfully")
        else:
            print(f"Failed to send: {response.status_code}")
    except Exception as e:
        print(f"Error: {e}")

def check_for_tokens():
    # Placeholder for now
    message = "**No strong new setups right now.**\n\nBot is running and checking every 2 minutes."
    send_discord_message(message)

if __name__ == "__main__":
    print("Memecoin webhook bot started...")
    while True:
        print(f"[{datetime.now()}] Checking...")
        check_for_tokens()
        time.sleep(CHECK_INTERVAL)

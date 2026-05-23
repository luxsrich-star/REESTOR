import os
import json
import time
import logging
import requests
import gspread

from datetime import datetime

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

from oauth2client.service_account import ServiceAccountCredentials

# ================= LOG =================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

# ================= CONFIG =================
TOKEN = os.environ["TELEGRAM_TOKEN"]
TABLE_ID = os.environ["SPREADSHEET_ID"]
GOOGLE_KEY = json.loads(os.environ["GDRIVE_CREDENTIALS"])
SLUG = os.environ.get("SHOP_SLUG", "shop")

SITE = "https://b2bshopb2b.up.railway.app/api/admin"
SHOP_URL = f"https://b2bshopb2b.up.railway.app/api/shop/{SLUG}"

# ================= GOOGLE =================
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

gs = gspread.authorize(
    ServiceAccountCredentials.from_json_keyfile_dict(GOOGLE_KEY, scope)
)

sh = gs.open_by_key(TABLE_ID)

склад = sh.worksheet("СКЛАД")
фин = sh.worksheet("ФИНАНСЫ")
ист = sh.worksheet("ИСТОРИЯ")
тов = sh.worksheet("ТОВАРЫ")

# ================= MEMORY =================
last_ops = {}

# ================= MENU =================
def menu():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📦 Остатки"), KeyboardButton("💰 Прибыль")],
            [KeyboardButton("📋 История"), KeyboardButton("🗑 Очистить")]
        ],
        resize_keyboard=True
    )

# ================= HELPERS =================
def now():
    return datetime.now().strftime("%d.%m.%Y %H:%M:%S")


def is_duplicate(chat_id, text):
    key = f"{chat_id}:{text}"
    if key in last_ops:
        return True
    last_ops[key] = time.time()
    return False


# ================= PARSER =================
def parse(text):
    text = text.strip()
    op = "Продажа"

    if text.lower().startswith("закуп"):
        op = "Закуп"
        text = text[5:].strip()

    words = text.split()
    nums = []
    product_words = []

    for w in words:
        clean = w.replace("шт", "").replace("штук", "")
        if clean.isdigit():
            nums.append(int(clean))
        else:
            product_words.append(w)

    price = nums[0] if nums else None
    qty = nums[1] if len(nums) > 1 else 1

    return {
        "товар": " ".join(product_words),
        "цена": price,
        "количество": qty,
        "операция": op,
        "поставка": None
    }


# ================= API =================
def find_product(name):
    try:
        r = requests.get(
            f"{SITE}/find-product",
            params={"shopSlug": SLUG, "productName": name},
            timeout=10
        )
        d = r.json()

        # гибкая проверка
        if d.get("found") or d.get("success"):
            return d
    except:
        pass

    try:
        r = requests.get(SHOP_URL, timeout=10)
        data = r.json()

        products = data.get("products") or data.get("data") or []

        for p in products:
            pname = p.get("name", "").lower()
            if name.lower() in pname or pname in name.lower():
                return {
                    "found": True,
                    "productName": p["name"],
                    "price": p.get("price", 0),
                    "cost": p.get("cost", 0),
                    "stock": p.get("stock", 0)
                }
    except Exception as e:
        print("SEARCH ERROR:", e)

    return {"found": False}


def update_site(name, qty):
    try:
        r = requests.post(
            f"{SITE}/update-stock",
            json={
                "shopSlug": SLUG,
                "productName": name,
                "quantityChange": qty
            },
            timeout=10
        )
        return r.json()
    except:
        return {"success": False}


def write_sheets(data, site):
    date = datetime.now().strftime("%d.%m.%Y")

    qty = data["количество"]
    price = data["цена"] or site.get("price", 0)
    cost = site.get("cost", 0)

    if data["операция"] == "Продажа":
        склад.append_row([date, "Продажа", data["поставка"], data["товар"], 0, qty])
        revenue = price * qty
        profit = (price - cost) * qty if cost else 0
        фин.append_row([date, "Продажа", data["поставка"], data["товар"], revenue, profit])
    else:
        склад.append_row([date, "Закуп", data["поставка"], data["товар"], qty, 0])
        фин.append_row([date, "Закуп", data["поставка"], data["товар"], -(price * qty), 0])

    ист.append_row([
        date,
        data["операция"],
        data["товар"],
        price,
        qty,
        data["поставка"]
    ])


def process(data):
    site = find_product(data["товар"])

    if not site.get("found"):
        return {"ok": False}

    name = site["productName"]

    qty = data["количество"]
    delta = -qty if data["операция"] == "Продажа" else qty

    upd = update_site(name, delta)

    if not upd.get("success"):
        return {"ok": False}

    write_sheets(data, site)

    return {
        "ok": True,
        "product": name,
        "stock": upd.get("newStock", site.get("stock"))
    }


# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("REESTOR BOT v2.0", reply_markup=menu())


async def message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    text = update.message.text.strip()

    if is_duplicate(chat_id, text):
        return

    data = parse(text)

    # 🔴 DEBUG СЮДА
    print("INPUT:", text)
    print("PARSED:", data)

    result = process(data)

    # 🔴 И СЮДА
    print("FOUND:", result)

    if not result["ok"]:
        await update.message.reply_text("❌ Товар не найден или ошибка")
        return

    await update.message.reply_text(
        f"✅ {result['product']}\n📦 Остаток: {result['stock']}"
    )


# ================= RUN =================
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message))

    print("🚀 REESTOR v2.0 RUNNING")
    app.run_polling()
import os
import json
import requests
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import gspread
from oauth2client.service_account import ServiceAccountCredentials

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
GDRIVE_CREDENTIALS = json.loads(os.environ["GDRIVE_CREDENTIALS"])
SHOP_SLUG = os.environ.get("SHOP_SLUG", "shop")

SITE_API_BASE = "https://b2bshopb2b.up.railway.app/api/admin"
SITE_UPDATE_STOCK = f"{SITE_API_BASE}/update-stock"
SITE_FIND_PRODUCT = f"{SITE_API_BASE}/find-product"
SITE_CHECK_ACCESS = f"{SITE_API_BASE}/check-bot-access"
SITE_BIND_TG = f"{SITE_API_BASE}/bind-telegram"
SITE_CHECK_TG = f"{SITE_API_BASE}/check-telegram"

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(GDRIVE_CREDENTIALS, scope)
client = gspread.authorize(creds)
sheet = client.open_by_key(SPREADSHEET_ID)
ws_sklad = sheet.worksheet("СКЛАД")
ws_fin = sheet.worksheet("ФИНАНСЫ")
ws_history = sheet.worksheet("ИСТОРИЯ")
ws_tovary = sheet.worksheet("ТОВАРЫ")

user_states = {}

def main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📦 Остатки"), KeyboardButton("💰 Прибыль")],
        [KeyboardButton("📋 История"), KeyboardButton("🗑 Очистить")]
    ], resize_keyboard=True)

def load_synonyms():
    rows = ws_tovary.get_all_values()[1:]
    syns = {}
    for row in rows:
        if row and row[0]:
            main = row[0].strip()
            syns[main.lower()] = main
            if len(row) > 1 and row[1]:
                for s in row[1].split(","):
                    s = s.strip()
                    if s:
                        syns[s.lower()] = main
    return syns

def find_product_on_site(product_name):
    try:
        r = requests.get(SITE_FIND_PRODUCT, params={"shopSlug": SHOP_SLUG, "productName": product_name}, timeout=10)
        return r.json()
    except:
        return {"found": False}

def update_stock_on_site(product_name, quantity_change):
    try:
        r = requests.post(SITE_UPDATE_STOCK,
            json={"shopSlug": SHOP_SLUG, "productName": product_name, "quantityChange": quantity_change},
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=10)
        return r.json()
    except:
        return {"success": False}

def parse_message(text):
    synonyms = load_synonyms()
    text = text.strip()
    
    if text.lower().startswith("закуп"):
        operation = "Закуп"
        text = text[5:].strip()
    else:
        operation = "Продажа"
    
    supply = None
    if "поставка" in text:
        parts = text.split("поставка")
        text = parts[0].strip()
        tail = parts[1].strip()
        supply = int(tail.split()[0]) if tail else None
    
    qty = 1
    words = text.split()
    for i, w in enumerate(words):
        clean = w.replace("шт", "").replace("штуки", "").replace("штук", "")
        if w in ("шт", "штуки", "штук") or (clean.isdigit() and i == len(words)-1):
            try:
                qty = int(clean) if clean.isdigit() else int(words[i-1])
                if clean.isdigit():
                    words.pop(i)
                else:
                    words.pop(i)
                    words.pop(i-1)
            except:
                qty = 1
            text = " ".join(words)
            break
    
    price = None
    words = text.split()
    for i, w in enumerate(reversed(words)):
        if w.isdigit():
            price = int(w)
            words.pop(len(words)-1-i)
            text = " ".join(words)
            break
    
    product = text.strip()
    product_lower = product.lower()
    if product_lower in synonyms:
        product = synonyms[product_lower]
    
    return {
        "товар": product,
        "цена": price,
        "поставка": supply,
        "количество": qty,
        "клиент": None,
        "операция": operation
    }

def write_to_sheets(data, site_data):
    today = datetime.now().strftime("%d.%m.%Y")
    qty = data["количество"]
    if data["операция"] == "Продажа":
        ws_sklad.append_row([today, "Продажа", data["поставка"], data["товар"], 0, qty])
    else:
        ws_sklad.append_row([today, "Закуп", data["поставка"], data["товар"], qty, 0])
    price = data["цена"] or site_data.get("price", 0)
    cost = site_data.get("cost", 0)
    if data["операция"] == "Продажа":
        revenue = price * qty
        profit = (price - cost) * qty if cost else 0
        ws_fin.append_row([today, "Продажа", data["поставка"], data["товар"], revenue, f"Прибыль: {profit}"])
    else:
        ws_fin.append_row([today, "Закуп", data["поставка"], data["товар"], -(price * qty), ""])
    client = data.get("клиент") or ""
    profit_val = ((price - cost) * qty) if (cost and data["операция"] == "Продажа") else ""
    ws_history.append_row([today, data["операция"], data["товар"], price, qty, data["поставка"], client, profit_val])

def delete_record_by_row(row_number):
    all_history = ws_history.get_all_values()
    if row_number < 2 or row_number > len(all_history):
        return None
    row = all_history[row_number - 1]
    if not row or not row[0]:
        return None
    operation = row[1]
    product_name = row[2]
    qty = int(row[4]) if row[4] else 1
    date = row[0]
    ws_history.delete_rows(row_number)
    all_sklad = ws_sklad.get_all_values()
    for i in range(len(all_sklad) - 1, 0, -1):
        if all_sklad[i] and all_sklad[i][0] == date and all_sklad[i][3] == product_name:
            ws_sklad.delete_rows(i + 1)
            break
    all_fin = ws_fin.get_all_values()
    for i in range(len(all_fin) - 1, 0, -1):
        if all_fin[i] and all_fin[i][0] == date and all_fin[i][3] == product_name:
            ws_fin.delete_rows(i + 1)
            break
    if operation == "Продажа":
        update_stock_on_site(product_name, qty)
    elif operation == "Закуп":
        update_stock_on_site(product_name, -qty)
    return product_name

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    try:
        r = requests.get(SITE_CHECK_TG, params={"slug": SHOP_SLUG, "telegramId": chat_id}, timeout=10)
        if r.status_code == 200 and r.json().get("success"):
            await update.message.reply_text(f"👋 С возвращением! Магазин: {r.json().get('shopName', SHOP_SLUG)}", reply_markup=main_keyboard())
            return
    except:
        pass
    await update.message.reply_text("🔐 Введите slug магазина:")
    user_states[chat_id] = {"state": "waiting_slug"}

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    text = update.message.text.strip()
    state = user_states.get(chat_id, {}).get("state")

    if state == "waiting_delete_row":
        try:
            row_num = int(text)
            result = delete_record_by_row(row_num)
            if result:
                await update.message.reply_text(f"🗑 Удалена запись: {result}. Остаток восстановлен.")
            else:
                await update.message.reply_text("❌ Неверный номер.")
        except:
            await update.message.reply_text("❌ Введите число.")
        user_states.pop(chat_id, None)
        return

    if text == "📦 Остатки":
        await cmd_ostatki(update, context)
        return
    elif text == "💰 Прибыль":
        await cmd_balance(update, context)
        return
    elif text == "📋 История":
        await cmd_history(update, context)
        return
    elif text == "🗑 Очистить":
        user_states[chat_id] = {"state": "waiting_delete_row"}
        await update.message.reply_text("Введите номер строки для удаления:")
        return

    if state == "waiting_slug":
        user_states[chat_id] = {"state": "waiting_access_code", "data": {"slug": text}}
        await update.message.reply_text("🔑 Введите код доступа:")
        return
    elif state == "waiting_access_code":
        user_states[chat_id] = {"state": "waiting_verify_code", "data": {"slug": user_states[chat_id]["data"]["slug"], "access_code": text}}
        await update.message.reply_text("🔢 Введите код подтверждения:")
        return
    elif state == "waiting_verify_code":
        slug = user_states[chat_id]["data"]["slug"]
        access_code = user_states[chat_id]["data"]["access_code"]
        verify_code = text
        try:
            r = requests.get(SITE_CHECK_ACCESS, params={"slug": slug, "accessCode": access_code, "verifyCode": verify_code}, timeout=10)
            data = r.json()
            if data.get("success"):
                requests.post(SITE_BIND_TG, json={"shopSlug": slug, "telegramId": chat_id}, timeout=10)
                user_states.pop(chat_id, None)
                await update.message.reply_text(f"✅ Доступ разрешён! Магазин: {data.get('shopName', slug)}", reply_markup=main_keyboard())
            else:
                await update.message.reply_text(f"❌ Ошибка: {data.get('error', 'неверные данные')}. /start")
        except:
            await update.message.reply_text("⚠️ Сайт недоступен.")
        return

    data = parse_message(text)

    site_data = find_product_on_site(data["товар"])
    if not site_data.get("found"):
        await update.message.reply_text(f"❌ Товар «{data['товар']}» не найден на сайте.")
        return

    if data["цена"] is None:
        data["цена"] = site_data.get("price", 0)

    qty_change = -data["количество"] if data["операция"] == "Продажа" else data["количество"]
    update_result = update_stock_on_site(data["товар"], qty_change)

    write_to_sheets(data, site_data)

    price = data["цена"]
    qty = data["количество"]
    cost = site_data.get("cost", 0)
    revenue = price * qty
    profit = (price - cost) * qty if cost else 0
    new_stock = update_result.get("newStock", site_data.get("currentStock", 0) + qty_change)

    msg = f"💰 Продажа: {data['товар']}\n💵 Цена: {price} руб × {qty} шт\n📦 Поставка: {data['поставка']}\n"
    if data.get("клиент"):
        msg += f"👤 Клиент: {data['клиент']}\n"
    msg += f"🛒 Оборот: {revenue} руб\n"
    if cost:
        msg += f"🟢 Чистая прибыль: {profit} руб\n"
    msg += f"📦 Осталось: {new_stock} шт"
    await update.message.reply_text(msg)

async def cmd_ostatki(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        r = requests.get(f"https://b2bshopb2b.up.railway.app/api/shop/{SHOP_SLUG}", timeout=10)
        data = r.json()
        products = data.get("products", [])
        categories = data.get("categories", [])
        cat_map = {c["id"]: c["name"] for c in categories}
        parent_map = {c["id"]: c["parentId"] for c in categories if c.get("parentId")}
        grouped = {}
        for p in products:
            if p.get("hidden"):
                continue
            cat_name = cat_map.get(p.get("categoryId", ""), "Другое")
            pid = parent_map.get(p.get("categoryId", ""))
            if pid and pid in cat_map:
                cat_name = f"{cat_name} ({cat_map[pid]})"
            if cat_name not in grouped:
                grouped[cat_name] = []
            name = p["name"]
            for prefix in ["D.L.T.A. ", "DLTA ", "CATS WILL ", "CATSWILL ", "Fedors ", "Fedrs "]:
                if name.startswith(prefix):
                    name = name[len(prefix):]
                    break
            grouped[cat_name].append(f"• {name.strip()} — {p['stock']} шт | {p['price']} руб")
        if not grouped:
            await update.message.reply_text("📦 Склад пуст")
            return
        msg = "📦 ОСТАТКИ:\n"
        for cat_name, items in grouped.items():
            msg += f"\n📌 {cat_name}\n" + "\n".join(items) + "\n"
        await update.message.reply_text(msg)
    except:
        await update.message.reply_text("⚠️ Не удалось загрузить остатки")

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = ws_fin.get_all_values()[1:]
    total = sum(float(row[4]) for row in rows if row[4])
    await update.message.reply_text(f"💸 Текущий баланс: {total:,.0f} руб")

async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    all_rows = ws_history.get_all_values()
    data_rows = [r for r in all_rows[1:] if r and len(r) >= 5 and r[0]]
    last = data_rows[-5:] if len(data_rows) > 5 else data_rows
    if not last:
        await update.message.reply_text("📋 История пуста")
        return
    msg = "📋 Последние операции:\n\n"
    for row in reversed(last):
        idx = all_rows.index(row) + 1
        msg += f"#{idx} {row[0]} — {row[1]}: {row[2]}, {row[3]} руб × {row[4]} шт\n"
    msg += "\n🗑 Для удаления: кнопка 'Очистить' и введите номер."
    await update.message.reply_text(msg)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ Продажа: Товар Цена поставка Номер\n"
        "Пример: Adrenaline Апельсин 450 поставка 1\n\n"
        "📦 Остатки | 💰 Прибыль | 📋 История | 🗑 Очистить"
    )

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ostatki", cmd_ostatki))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🚀 REESTOR запущен")
    app.run_polling()
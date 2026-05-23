import os
import json
import requests
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ========== КОНФИГУРАЦИЯ ==========
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
DEEPSEEK_API_KEY = os.environ["DEEPSEEK_API_KEY"]
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
GDRIVE_CREDENTIALS = json.loads(os.environ["GDRIVE_CREDENTIALS"])

SITE_API_BASE = "https://b2bshopb2b.up.railway.app/api/admin"
SITE_UPDATE_STOCK = f"{SITE_API_BASE}/update-stock"
SITE_FIND_PRODUCT = f"{SITE_API_BASE}/find-product"
SITE_CHECK_ACCESS = f"{SITE_API_BASE}/check-bot-access"
SITE_BIND_TG = f"{SITE_API_BASE}/bind-telegram"
SITE_CHECK_TG = f"{SITE_API_BASE}/check-telegram"
SHOP_SLUG = os.environ.get("SHOP_SLUG", "shop")

# ========== GOOGLE SHEETS ==========
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(GDRIVE_CREDENTIALS, scope)
client = gspread.authorize(creds)
sheet = client.open_by_key(SPREADSHEET_ID)
ws_sklad = sheet.worksheet("СКЛАД")
ws_fin = sheet.worksheet("ФИНАНСЫ")
ws_history = sheet.worksheet("ИСТОРИЯ")
ws_tovary = sheet.worksheet("ТОВАРЫ")

user_states = {}

# ========== МЕНЮ ==========
def main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📦 Остатки"), KeyboardButton("💰 Прибыль")],
        [KeyboardButton("📋 История"), KeyboardButton("🗑 Очистить")]
    ], resize_keyboard=True)

# ========== СИНОНИМЫ ==========
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

# ========== API САЙТА ==========
def find_product_on_site(product_name):
    try:
        r = requests.get(SITE_FIND_PRODUCT, params={"shopSlug": SHOP_SLUG, "productName": product_name}, timeout=10)
        return r.json()
    except:
        return {"found": False}

def update_stock_on_site(product_name, quantity_change):
    try:
        r = requests.post(SITE_UPDATE_STOCK, json={"shopSlug": SHOP_SLUG, "productName": product_name, "quantityChange": quantity_change}, timeout=10)
        return r.json()
    except:
        return {"success": False}

# ========== DEEPSEEK ==========
def parse_message(text):
    synonyms = load_synonyms()
    syns_text = "\n".join([f"  {k} -> {v}" for k, v in list(synonyms.items())[:50]])
    sp = f"Extract JSON: product, price, supply, quantity, client, operation. Synonyms: {syns_text}. Return JSON only."
    r = requests.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
        json={"model": "deepseek-chat", "messages": [{"role": "system", "content": sp}, {"role": "user", "content": text}], "temperature": 0.0, "response_format": {"type": "json_object"}},
        timeout=15
    )
    result = json.loads(r.json()["choices"][0]["message"]["content"])
    data = {
        "товар": result.get("product") or result.get("товар") or result.get("name", ""),
        "цена": result.get("price") or result.get("цена"),
        "поставка": result.get("supply") or result.get("поставка"),
        "количество": result.get("quantity") or result.get("количество") or 1,
        "клиент": result.get("client") or result.get("клиент"),
        "операция": "Продажа" if result.get("operation") != "Закуп" else "Закуп"
    }
    return data

# ========== ЗАПИСЬ В ТАБЛИЦУ ==========
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

# ========== УДАЛЕНИЕ ==========
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

# ========== КОМАНДЫ ==========
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
                await update.message.reply_text(f"🗑 Удалена запись: {result}. Остаток на сайте восстановлен.")
            else:
                await update.message.reply_text("❌ Неверный номер строки.")
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
        await update.message.reply_text("Введите номер строки для удаления (# из Истории):")
        return

    if state == "waiting_slug":
        user_states[chat_id] = {"state": "waiting_access_code", "data": {"slug": text}}
        await update.message.reply_text("🔑 Введите код доступа:")
        return
    elif state == "waiting_access_code":
        slug = user_states[chat_id]["data"]["slug"]
        user_states[chat_id] = {"state": "waiting_verify_code", "data": {"slug": slug, "access_code": text}}
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

    try:
        data = parse_message(text)
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка парсинга: {e}")
        return

    site_data = find_product_on_site(data["товар"])
    if not site_data.get("found"):
        await update.message.reply_text(f"❌ Товар «{data['товар']}» не найден на сайте.")
        return

    if data["цена"] is None:
        data["цена"] = site_data.get("price", 0)

    qty_change = -data["количество"] if data["операция"] == "Продажа" else data["количество"]
    update_result = update_stock_on_site(data["товар"], qty_change)
    if not update_result.get("success"):
        await update.message.reply_text("⚠️ Сайт не обновлён. Запись в таблицу сделана.")

    write_to_sheets(data, site_data)

    price = data["цена"]
    qty = data["количество"]
    cost = site_data.get("cost", 0)
    revenue = price * qty
    profit = (price - cost) * qty if cost else 0
    if update_result.get("success"):
        new_stock = update_result.get("newStock", site_data.get("currentStock", 0) + qty_change)
    else:
        new_stock = site_data.get("currentStock", 0)

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
        cat_map = {}
        for cat in categories:
            cat_map[cat["id"]] = cat["name"]
        parent_map = {}
        for cat in categories:
            if cat.get("parentId"):
                parent_map[cat["id"]] = cat["parentId"]
        grouped = {}
        for p in products:
            if p.get("hidden"):
                continue
            cat_id = p.get("categoryId", "other")
            cat_name = cat_map.get(cat_id, "Другое")
            parent_id = parent_map.get(cat_id)
            if parent_id:
                parent_name = cat_map.get(parent_id, "")
                if parent_name:
                    cat_name = f"{cat_name} ({parent_name})"
            if cat_name not in grouped:
                grouped[cat_name] = []
            name = p["name"]
            for prefix in ["D.L.T.A. ", "DLTA ", "CATS WILL ", "CATSWILL ", "Fedors ", "Fedrs "]:
                if name.startswith(prefix):
                    name = name[len(prefix):]
                    break
            name = name.strip()
            grouped[cat_name].append(f"• {name} — {p['stock']} шт | {p['price']} руб")
        if not grouped:
            await update.message.reply_text("📦 Склад пуст")
            return
        msg = "📦 ОСТАТКИ:\n"
        emoji_map = {"Шайбы": "🟢", "Жижа": "🟣", "D. L. T. A": "🟢", "CATSWILL": "🟣", "Fedrs": "🔵"}
        for cat_name, items in grouped.items():
            emoji = emoji_map.get(cat_name, "📌")
            msg += f"\n{emoji} {cat_name}\n"
            msg += "\n".join(items) + "\n"
        await update.message.reply_text(msg)
    except:
        await update.message.reply_text("⚠️ Не удалось загрузить остатки с сайта")

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = ws_fin.get_all_values()[1:]
    total = sum(float(row[4]) for row in rows if row[4])
    await update.message.reply_text(f"💸 Текущий баланс: {total:,.0f} руб")

async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    all_rows = ws_history.get_all_values()
    data_rows = [row for row in all_rows[1:] if row and len(row) >= 5 and row[0]]
    last = data_rows[-5:] if len(data_rows) > 5 else data_rows
    if not last:
        await update.message.reply_text("📋 История пуста")
        return
    msg = "📋 Последние операции:\n\n"
    for row in reversed(last):
        idx = all_rows.index(row) + 1
        client = f" | {row[6]}" if len(row) > 6 and row[6] else ""
        profit = f" | +{row[7]} руб" if len(row) > 7 and row[7] else ""
        msg += f"#{idx} {row[0]} — {row[1]}: {row[2]}, {row[3]} руб × {row[4]} шт{client}{profit}\n"
    msg += "\n🗑 Для удаления: нажмите кнопку 'Очистить' в меню и введите номер."
    await update.message.reply_text(msg)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ Как работать:\n\n"
        "Продажа:\n"
        "DLTA адреналин голд 450 поставка 4\n"
        "DLTA адреналин голд поставка 4 2 шт\n"
        "DLTA адреналин голд 450 поставка 4 primer\n\n"
        "📦 Остатки — что на складе\n"
        "💰 Прибыль — баланс\n"
        "📋 История — последние продажи\n"
        "🗑 Очистить — удалить запись по номеру"
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
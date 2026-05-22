import os
import json
import requests
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
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

# ========== ХРАНИЛИЩЕ СЕССИЙ ==========
user_states = {}  # chat_id -> {"state": "...", "data": {...}}

# ========== ГЛАВНОЕ МЕНЮ ==========
def main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📦 Остатки"), KeyboardButton("💰 Прибыль")],
        [KeyboardButton("📋 История"), KeyboardButton("🗑 Очистить")]
    ], resize_keyboard=True)

# ========== ЗАГРУЗКА СИНОНИМОВ ==========
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

# ========== ПРОВЕРКА ТОВАРА НА САЙТЕ ==========
def find_product_on_site(product_name):
    try:
        r = requests.get(SITE_FIND_PRODUCT, params={
            "shopSlug": SHOP_SLUG,
            "productName": product_name
        }, timeout=10)
        return r.json()
    except:
        return {"found": False, "error": "site_unreachable"}

# ========== ОБНОВЛЕНИЕ ОСТАТКА НА САЙТЕ ==========
def update_stock_on_site(product_name, quantity_change):
    try:
        r = requests.post(SITE_UPDATE_STOCK, json={
            "shopSlug": SHOP_SLUG,
            "productName": product_name,
            "quantityChange": quantity_change
        }, timeout=10)
        return r.json()
    except:
        return {"success": False, "error": "site_unreachable"}

# ========== ПАРСИНГ ЧЕРЕЗ DEEPSEEK ==========
def parse_message(text):
    synonyms = load_synonyms()
    syns_text = "\n".join([f"  {k} → {v}" for k, v in list(synonyms.items())[:50]])
    
    system_prompt = f"""Ты — парсер для складского бота. Извлеки из сообщения строгий JSON.

ПРАВИЛА:
- Если сообщение начинается с "Закуп" — операция "Закуп". Иначе "Продажа".
- Товар: приведи к каноническому названию из списка синонимов.
- Если товара нет в синонимах — оставь как есть, но каждое слово с Большой Буквы.
- Цена: число перед "поставка". Если нет — null.
- Поставка: число после слова "поставка". Если нет — null.
- Количество: число перед "шт". Если нет — 1.
- Клиент: слово после номера поставки, если это не число и не "шт". Если нет — null.

СИНОНИМЫ:
{syns_text}

Верни ТОЛЬКО JSON без пояснений:
{{"товар":"...","цена":число или null,"поставка":число или null,"количество":число,"клиент":"...","операция":"Продажа/Закуп"}}"""
    
    r = requests.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            "temperature": 0.0,
            "response_format": {"type": "json_object"}
        },
        timeout=15
    )
    return json.loads(r.json()["choices"][0]["message"]["content"])

# ========== ЗАПИСЬ В ТАБЛИЦУ ==========
def write_to_sheets(data, site_data):
    today = datetime.now().strftime("%d.%m.%Y")
    
    # СКЛАД
    qty = data["количество"]
    if data["операция"] == "Продажа":
        ws_sklad.append_row([today, "Продажа", data["поставка"], data["товар"], 0, qty])
    else:
        ws_sklad.append_row([today, "Закуп", data["поставка"], data["товар"], qty, 0])
    
    # ФИНАНСЫ
    price = data["цена"] or site_data.get("price", 0)
    cost = site_data.get("cost", 0)
    
    if data["операция"] == "Продажа":
        revenue = price * qty
        profit = (price - cost) * qty if cost else 0
        ws_fin.append_row([today, "Продажа", data["поставка"], data["товар"], revenue, f"Прибыль: {profit}"])
    else:
        ws_fin.append_row([today, "Закуп", data["поставка"], data["товар"], -(price * qty), ""])
    
    # ИСТОРИЯ
    client = data.get("клиент") or ""
    profit_val = ((price - cost) * qty) if (cost and data["операция"] == "Продажа") else ""
    ws_history.append_row([today, data["операция"], data["товар"], price, qty, data["поставка"], client, profit_val])
    # ========== УДАЛЕНИЕ ПОСЛЕДНЕЙ ЗАПИСИ ==========
def delete_last_record():
    # Найти последнюю строку в ИСТОРИИ
    rows = ws_history.get_all_values()
    last_row = None
    for row in reversed(rows):
        if row and row[0]:
            last_row = row
            break
    if not last_row:
        return None
    
    # last_row = [Дата, Операция, Товар, Цена, Кол-во, Поставка, Клиент, Прибыль]
    operation = last_row[1]
    product_name = last_row[2]
    qty = int(last_row[4]) if last_row[4] else 1
    
    # Удалить последнюю строку в ИСТОРИИ
    all_history = ws_history.get_all_values()
    for i in range(len(all_history) - 1, 0, -1):
        if all_history[i] and all_history[i][0]:
            ws_history.delete_rows(i + 1)
            break
    
    # Удалить последнюю строку в СКЛАДЕ
    all_sklad = ws_sklad.get_all_values()
    for i in range(len(all_sklad) - 1, 0, -1):
        if all_sklad[i] and all_sklad[i][0]:
            ws_sklad.delete_rows(i + 1)
            break
    
    # Удалить последнюю строку в ФИНАНСАХ
    all_fin = ws_fin.get_all_values()
    for i in range(len(all_fin) - 1, 0, -1):
        if all_fin[i] and all_fin[i][0]:
            ws_fin.delete_rows(i + 1)
            break
    
    # Вернуть остаток на сайт
    if operation == "Продажа":
        update_stock_on_site(product_name, qty)
    elif operation == "Закуп":
        update_stock_on_site(product_name, -qty)
    
    return product_name

# ========== КОМАНДА /start ==========
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    
    # Проверяем, привязан ли уже
    try:
        r = requests.get(SITE_CHECK_TG, params={"slug": SHOP_SLUG, "telegramId": chat_id}, timeout=10)
        if r.status_code == 200 and r.json().get("success"):
            await update.message.reply_text(
                f"👋 С возвращением! Магазин: {r.json().get('shopName', SHOP_SLUG)}",
                reply_markup=main_keyboard()
            )
            return
    except:
        pass
    
    await update.message.reply_text("🔐 Введите slug магазина:")
    user_states[chat_id] = {"state": "waiting_slug"}

# ========== ОБРАБОТЧИК ТЕКСТА ==========
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    text = update.message.text.strip()
    
    # ===== МЕНЮ (КНОПКИ) =====
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
        result = delete_last_record()
        if result:
            await update.message.reply_text(f"🗑 Удалена последняя запись: {result}. Остаток на сайте восстановлен.")
        else:
            await update.message.reply_text("📋 Нечего удалять.")
        return
    
    # ===== АВТОРИЗАЦИЯ =====
    state = user_states.get(chat_id, {}).get("state")
    
    if state == "waiting_slug":
        user_states[chat_id] = {"state": "waiting_access_code", "data": {"slug": text}}
        await update.message.reply_text("🔑 Введите код доступа:")
        return
    
    elif state == "waiting_access_code":
        slug = user_states[chat_id]["data"]["slug"]
        access_code = text
        user_states[chat_id] = {"state": "waiting_verify_code", "data": {"slug": slug, "access_code": access_code}}
        await update.message.reply_text("🔢 Введите код подтверждения:")
        return
    
    elif state == "waiting_verify_code":
        slug = user_states[chat_id]["data"]["slug"]
        access_code = user_states[chat_id]["data"]["access_code"]
        verify_code = text
        
        try:
            r = requests.get(SITE_CHECK_ACCESS, params={
                "slug": slug, "accessCode": access_code, "verifyCode": verify_code
            }, timeout=10)
            data = r.json()
            
            if data.get("success"):
                # Привязываем Telegram ID
                requests.post(SITE_BIND_TG, json={
                    "shopSlug": slug, "telegramId": chat_id
                }, timeout=10)
                
                user_states.pop(chat_id, None)
                await update.message.reply_text(
                    f"✅ Доступ разрешён! Магазин: {data.get('shopName', slug)}",
                    reply_markup=main_keyboard()
                )
            else:
                await update.message.reply_text(f"❌ Ошибка: {data.get('error', 'неверные данные')}. Попробуйте /start")
        except:
            await update.message.reply_text("⚠️ Сайт недоступен. Попробуйте позже.")
        return
    
    # ===== ПРОДАЖА =====
    try:
        data = parse_message(text)
    except Exception as e:
        await update.message.reply_text("❌ Не смог распознать сообщение. Попробуйте:\n`DLTA адреналин голд 450 поставка 4`")
        return
    
    # Проверяем товар на сайте
    site_data = find_product_on_site(data["товар"])
    
    if not site_data.get("found"):
        await update.message.reply_text(f"❌ Товар «{data['товар']}» не найден на сайте. Создайте его в админке.")
        return
    
    # Если цена не указана — берём с сайта
    if data["цена"] is None:
        data["цена"] = site_data.get("price", 0)
    
    # Обновляем остаток на сайте
    qty = -data["количество"] if data["операция"] == "Продажа" else data["количество"]
    update_result = update_stock_on_site(data["товар"], qty)
    
    if not update_result.get("success"):
        await update.message.reply_text(f"⚠️ Не удалось обновить сайт: {update_result.get('error')}. Запись в таблицу сделана.")
    
    # Пишем в Таблицу
    write_to_sheets(data, site_data)
    
    # Ответ
    price = data["цена"]
    qty = data["количество"]
    cost = site_data.get("cost", 0)
    revenue = price * qty
    profit = (price - cost) * qty if cost else 0
    new_stock = update_result.get("newStock", site_data.get("currentStock", 0) + qty)
    
    msg = f"💰 Продажа: {data['товар']}\n"
    msg += f"💵 Цена: {price} руб × {qty} шт\n"
    msg += f"📦 Поставка: {data['поставка']}\n"
    if data.get("клиент"):
        msg += f"👤 Клиент: {data['клиент']}\n"
    msg += f"🛒 Оборот: {revenue} руб\n"
    if cost:
        msg += f"🟢 Чистая: {profit} руб\n"
    msg += f"📦 Осталось: {new_stock} шт"
    
    await update.message.reply_text(msg)

# ========== КОМАНДЫ ==========
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
            grouped[cat_name].append(f"• {name} - {p['stock']} шт | {p['price']} руб")
        
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
    rows = ws_history.get_all_values()[-15:]
    if not rows or (len(rows) == 1 and not rows[0][0]):
        await update.message.reply_text("📋 История пуста")
        return
    
    msg = "📋 Последние операции:\n\n"
    for row in reversed(rows[-15:]):
        if row and row[0]:
            client = f" | {row[6]}" if row[6] else ""
            profit = f" | +{row[7]} руб" if row[7] else ""
            msg += f"{row[0]} — {row[1]}: {row[2]}, {row[3]} руб × {row[4]} шт{client}{profit}\n"
    await update.message.reply_text(msg)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ Как работать:\n\n"
        "Продажа:\n"
        "`DLTA адреналин голд 450 поставка 4`\n"
        "`DLTA адреналин голд поставка 4 2 шт`\n"
        "`DLTA адреналин голд 450 поставка 4 primer`\n\n"
        "📦 Остатки — что на складе\n"
        "💰 Прибыль — баланс\n"
        "📋 История — последние продажи"
    )

# ========== ЗАПУСК ==========
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

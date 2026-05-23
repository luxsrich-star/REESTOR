import os
import json
import requests
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ========== КОНФИГ ==========
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
GDRIVE_CREDENTIALS = json.loads(os.environ["GDRIVE_CREDENTIALS"])
SHOP_SLUG = os.environ.get("SHOP_SLUG", "shop")

SITE_API = "https://b2bshopb2b.up.railway.app/api/admin"
SITE_SHOP = f"https://b2bshopb2b.up.railway.app/api/shop/{SHOP_SLUG}"

# ========== GOOGLE ==========
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(GDRIVE_CREDENTIALS, scope)
gs = gspread.authorize(creds)
sh = gs.open_by_key(SPREADSHEET_ID)
sklad = sh.worksheet("СКЛАД")
fin = sh.worksheet("ФИНАНСЫ")
hist = sh.worksheet("ИСТОРИЯ")
tov = sh.worksheet("ТОВАРЫ")

state = {}

# ========== МЕНЮ ==========
def menu():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📦 Остатки"), KeyboardButton("💰 Прибыль")],
        [KeyboardButton("📋 История"), KeyboardButton("🗑 Очистить")]
    ], resize_keyboard=True)

# ========== СИНОНИМЫ ==========
def syns():
    r = {}
    for row in tov.get_all_values()[1:]:
        if row and row[0]:
            m = row[0].strip()
            r[m.lower()] = m
            if len(row) > 1 and row[1]:
                for s in row[1].split(","):
                    s = s.strip()
                    if s:
                        r[s.lower()] = m
    return r

# ========== САЙТ ==========
def site_find(name):
    try:
        r = requests.get(f"{SITE_API}/find-product", params={"shopSlug": SHOP_SLUG, "productName": name}, timeout=10)
        return r.json()
    except:
        return {"found": False}

def site_update(name, qty):
    try:
        r = requests.post(f"{SITE_API}/update-stock",
            json={"shopSlug": SHOP_SLUG, "productName": name, "quantityChange": qty},
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=10)
        return r.json()
    except:
        return {"success": False}

# ========== ПАРСИНГ ==========
def parse(text):
    s = syns()
    text = text.strip()
    op = "Продажа"
    if text.lower().startswith("закуп"):
        op = "Закуп"
        text = text[5:].strip()

    # поставка
    sup = None
    if "поставка" in text:
        p = text.split("поставка")
        text = p[0].strip()
        tail = p[1].strip().split()
        if tail and tail[0].isdigit():
            sup = int(tail[0])

    # разбираем слова
    words = text.split()
    nums = []
    prod = []
    for w in words:
        c = w.replace("шт", "").replace("штук", "").replace("штуки", "")
        if c.isdigit():
            nums.append(int(c))
        elif w in ("шт", "штук", "штуки"):
            pass
        else:
            prod.append(w)

    price = nums[0] if nums else None
    qty = nums[1] if len(nums) > 1 else 1

    product = " ".join(prod).strip()
    pl = product.lower()
    if pl in s:
        product = s[pl]

    return {"товар": product, "цена": price, "поставка": sup, "количество": qty, "клиент": None, "операция": op}

# ========== ЗАПИСЬ ==========
def write(data, sd):
    t = datetime.now().strftime("%d.%m.%Y")
    q = data["количество"]
    sklad.append_row([t, data["операция"], data["поставка"], data["товар"], q if data["операция"] == "Закуп" else 0, q if data["операция"] == "Продажа" else 0])
    price = data["цена"] or sd.get("price", 0)
    cost = sd.get("cost", 0)
    if data["операция"] == "Продажа":
        rev = price * q
        prof = (price - cost) * q if cost else 0
        fin.append_row([t, "Продажа", data["поставка"], data["товар"], rev, f"Прибыль: {prof}"])
    else:
        fin.append_row([t, "Закуп", data["поставка"], data["товар"], -(price * q), ""])
    cl = data.get("клиент") or ""
    pv = ((price - cost) * q) if (cost and data["операция"] == "Продажа") else ""
    hist.append_row([t, data["операция"], data["товар"], price, q, data["поставка"], cl, pv])

# ========== УДАЛЕНИЕ ==========
def del_row(n):
    rows = hist.get_all_values()
    if n < 2 or n > len(rows):
        return None
    row = rows[n - 1]
    if not row or not row[0]:
        return None
    op = row[1]
    nm = row[2]
    q = int(row[4]) if row[4] else 1
    dt = row[0]
    hist.delete_rows(n)
    for i in range(len(sklad.get_all_values()) - 1, 0, -1):
        if sklad.get_all_values()[i] and sklad.get_all_values()[i][0] == dt and sklad.get_all_values()[i][3] == nm:
            sklad.delete_rows(i + 1)
            break
    for i in range(len(fin.get_all_values()) - 1, 0, -1):
        if fin.get_all_values()[i] and fin.get_all_values()[i][0] == dt and fin.get_all_values()[i][3] == nm:
            fin.delete_rows(i + 1)
            break
    if op == "Продажа":
        site_update(nm, q)
    elif op == "Закуп":
        site_update(nm, -q)
    return nm

# ========== СТАРТ ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.message.chat_id
    try:
        r = requests.get(f"{SITE_API}/check-telegram", params={"slug": SHOP_SLUG, "telegramId": cid}, timeout=10)
        if r.status_code == 200 and r.json().get("success"):
            await update.message.reply_text(f"👋 С возвращением! Магазин: {r.json().get('shopName', SHOP_SLUG)}", reply_markup=menu())
            return
    except:
        pass
    await update.message.reply_text("🔐 Введите slug магазина:")
    state[cid] = {"s": "slug"}

# ========== СООБЩЕНИЯ ==========
async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.message.chat_id
    txt = update.message.text.strip()
    st = state.get(cid, {}).get("s")

    if st == "del":
        try:
            r = del_row(int(txt))
            if r:
                await update.message.reply_text(f"🗑 Удалено: {r}")
            else:
                await update.message.reply_text("❌ Неверный номер")
        except:
            await update.message.reply_text("❌ Введите число")
        state.pop(cid, None)
        return

    if txt == "📦 Остатки":
        await ostatki(update, context)
        return
    elif txt == "💰 Прибыль":
        await balance(update, context)
        return
    elif txt == "📋 История":
        await history(update, context)
        return
    elif txt == "🗑 Очистить":
        state[cid] = {"s": "del"}
        await update.message.reply_text("Введите номер строки для удаления:")
        return

    if st == "slug":
        state[cid] = {"s": "ac", "slug": txt}
        await update.message.reply_text("🔑 Введите код доступа:")
        return
    elif st == "ac":
        sl = state[cid]["slug"]
        state[cid] = {"s": "vc", "slug": sl, "ac": txt}
        await update.message.reply_text("🔢 Введите код подтверждения:")
        return
    elif st == "vc":
        sl = state[cid]["slug"]
        ac = state[cid]["ac"]
        vc = txt
        try:
            r = requests.get(f"{SITE_API}/check-bot-access", params={"slug": sl, "accessCode": ac, "verifyCode": vc}, timeout=10)
            d = r.json()
            if d.get("success"):
                requests.post(f"{SITE_API}/bind-telegram", json={"shopSlug": sl, "telegramId": cid}, timeout=10)
                state.pop(cid, None)
                await update.message.reply_text(f"✅ Доступ разрешён! Магазин: {d.get('shopName', sl)}", reply_markup=menu())
            else:
                await update.message.reply_text(f"❌ Ошибка: {d.get('error')}. /start")
        except:
            await update.message.reply_text("⚠️ Сайт недоступен")
        return

    # Продажа
    data = parse(txt)
    sd = site_find(data["товар"])
    if not sd.get("found"):
        await update.message.reply_text(f"❌ Товар «{data['товар']}» не найден на сайте.")
        return

    if data["цена"] is None:
        data["цена"] = sd.get("price", 0)

    qc = -data["количество"] if data["операция"] == "Продажа" else data["количество"]
    ur = site_update(data["товар"], qc)

    write(data, sd)

    price = data["цена"]
    qty = data["количество"]
    cost = sd.get("cost", 0)
    rev = price * qty
    prof = (price - cost) * qty if cost else 0
    ns = ur.get("newStock", sd.get("currentStock", 0) + qc)

    m = f"💰 Продажа: {data['товар']}\n💵 Цена: {price} руб × {qty} шт\n📦 Поставка: {data['поставка']}\n🛒 Оборот: {rev} руб\n"
    if cost:
        m += f"🟢 Чистая прибыль: {prof} руб\n"
    m += f"📦 Осталось: {ns} шт"
    await update.message.reply_text(m)

# ========== ОСТАТКИ ==========
async def ostatki(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        r = requests.get(SITE_SHOP, timeout=10)
        data = r.json()
        prods = data.get("products", [])
        cats = {c["id"]: c["name"] for c in data.get("categories", [])}
        parents = {c["id"]: c["parentId"] for c in data.get("categories", []) if c.get("parentId")}
        grp = {}
        for p in prods:
            if p.get("hidden"):
                continue
            cn = cats.get(p.get("categoryId", ""), "Другое")
            pid = parents.get(p.get("categoryId", ""))
            if pid and pid in cats:
                cn = f"{cn} ({cats[pid]})"
            if cn not in grp:
                grp[cn] = []
            nm = p["name"]
            for pr in ["D.L.T.A. ", "DLTA ", "CATS WILL ", "CATSWILL ", "Fedors ", "Fedrs "]:
                if nm.startswith(pr):
                    nm = nm[len(pr):]
                    break
            grp[cn].append(f"• {nm.strip()} — {p['stock']} шт | {p['price']} руб")
        if not grp:
            await update.message.reply_text("📦 Склад пуст")
            return
        msg = "📦 ОСТАТКИ:\n"
        for cn, items in grp.items():
            msg += f"\n📌 {cn}\n" + "\n".join(items) + "\n"
        await update.message.reply_text(msg)
    except:
        await update.message.reply_text("⚠️ Не удалось загрузить остатки")

# ========== БАЛАНС ==========
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = fin.get_all_values()[1:]
    total = sum(float(r[4]) for r in rows if r[4])
    await update.message.reply_text(f"💸 Баланс: {total:,.0f} руб")

# ========== ИСТОРИЯ ==========
async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = hist.get_all_values()
    data = [r for r in rows[1:] if r and len(r) >= 5 and r[0]]
    last = data[-5:] if len(data) > 5 else data
    if not last:
        await update.message.reply_text("📋 История пуста")
        return
    m = "📋 Последние операции:\n\n"
    for r in reversed(last):
        idx = rows.index(r) + 1
        m += f"#{idx} {r[0]} — {r[1]}: {r[2]}, {r[3]} руб × {r[4]} шт\n"
    m += "\n🗑 Для удаления: кнопка 'Очистить' и введите номер."
    await update.message.reply_text(m)

# ========== ХЕЛП ==========
async def helpcmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ℹ️ Продажа: Товар Цена поставка Номер\nПример: Adrenaline Апельсин 450 поставка 1")

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ostatki", ostatki))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("help", helpcmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
    print("🚀 REESTOR")
    app.run_polling()
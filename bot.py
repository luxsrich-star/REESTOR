import os, re, json, time, random, logging
import requests
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import gspread
from oauth2client.service_account import ServiceAccountCredentials

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

TOKEN       = os.environ["TELEGRAM_TOKEN"]
GOOGLE_KEY  = json.loads(os.environ["GDRIVE_CREDENTIALS"])
SITE        = os.environ.get("SITE_URL", "https://b2bshopb2b.up.railway.app") + "/api/admin"
SITE_BASE   = os.environ.get("SITE_URL", "https://b2bshopb2b.up.railway.app")
SUPERADMIN  = int(os.environ.get("SUPERADMIN_TG_ID", "0"))

_SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
_creds = ServiceAccountCredentials.from_json_keyfile_dict(GOOGLE_KEY, _SCOPE)
gc     = gspread.authorize(_creds)
_sheet_cache = {}

def get_sheets(sid):
    if sid in _sheet_cache:
        return _sheet_cache[sid]
    wb = gc.open_by_key(sid)
    sheets = {
        "sklad":   wb.worksheet("СКЛАД"),
        "finance": wb.worksheet("ФИНАНСЫ"),
        "history": wb.worksheet("ИСТОРИЯ"),
        "goods":   wb.worksheet("ТОВАРЫ"),
    }
    _sheet_cache[sid] = sheets
    return sheets

def gen_uid():
    return f"{int(time.time()*1000)}_{random.randint(1000,9999)}"

def keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📦 Остатки"), KeyboardButton("💰 Прибыль")],
        [KeyboardButton("📋 История"), KeyboardButton("🗑 Удалить запись")],
    ], resize_keyboard=True)

def get_ctx(bot_data, tg_id):
    return bot_data.get(f"shop_{tg_id}")

def save_ctx(bot_data, tg_id, slug, sid, name):
    bot_data[f"shop_{tg_id}"] = {"slug": slug, "sid": sid, "name": name}

# ── API ──────────────────────────────────────────────────────────────────────

def api_check_tg(slug, tg_id):
    try:
        r = requests.get(f"{SITE}/check-telegram",
                         params={"slug": slug, "telegramId": tg_id}, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log.error("check-telegram: %s", e)
    return {"success": False}

def api_check_access(slug, ac, vc):
    try:
        r = requests.get(f"{SITE}/check-bot-access",
                         params={"slug": slug, "accessCode": ac, "verifyCode": vc}, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log.error("check-bot-access: %s", e)
    return {"success": False, "error": "network_error"}

def api_bind(slug, tg_id, sid):
    try:
        r = requests.post(f"{SITE}/bind-telegram",
                          json={"shopSlug": slug, "telegramId": tg_id, "spreadsheetId": sid},
                          headers={"Content-Type": "application/json"}, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log.error("bind-telegram: %s", e)
    return {"success": False}

def api_find(slug, name):
    try:
        r = requests.get(f"{SITE}/find-product",
                         params={"shopSlug": slug, "productName": name}, timeout=10)
        if r.status_code == 200:
            d = r.json()
            if d.get("found"):
                return d
    except Exception as e:
        log.error("find-product: %s", e)
    return {"found": False}

def api_update(slug, name, change):
    body = {"shopSlug": slug, "productName": name, "quantityChange": change}
    try:
        r = requests.post(f"{SITE}/update-stock",
                          data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                          headers={"Content-Type": "application/json; charset=utf-8"},
                          timeout=10)
        if r.status_code == 200:
            return r.json()
        return {"success": False, "error": f"http_{r.status_code}"}
    except Exception as e:
        log.error("update-stock: %s", e)
        return {"success": False, "error": str(e)}

def api_catalog(slug):
    try:
        r = requests.get(f"{SITE_BASE}/api/shop/{slug}", timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log.error("catalog: %s", e)
    return {}

# ── Парсинг ──────────────────────────────────────────────────────────────────

def load_synonyms(sheets):
    result = {}
    try:
        rows = sheets["goods"].get_all_values()
        for row in rows[1:]:
            if not row or not row[0].strip():
                continue
            canon = row[0].strip()
            result[canon.lower()] = canon
            if len(row) > 1 and row[1].strip():
                for s in row[1].split(","):
                    s = s.strip()
                    if s:
                        result[s.lower()] = canon
    except Exception as e:
        log.error("load_synonyms: %s", e)
    return result

def find_canon(text, synonyms):
    tl = text.lower().strip()
    if tl in synonyms:
        return synonyms[tl]
    best, best_len = None, 0
    for syn, canon in synonyms.items():
        if syn in tl and len(syn) > best_len:
            best, best_len = canon, len(syn)
    return best

def parse_msg(text, sheets):
    synonyms = load_synonyms(sheets)
    text = text.strip()
    op = "Продажа"
    if text.lower().startswith("закуп"):
        op = "Закуп"
        text = text[5:].strip()

    delivery = None
    m = re.search(r'поставка\s+(\d+)', text, re.IGNORECASE)
    if m:
        delivery = int(m.group(1))
        text = text[:m.start()].strip()

    nums = [int(m2.group(1)) for m2 in
            re.finditer(r'\b(\d+)\s*(?:штук[иа]?|шт\.?)?\b', text, re.IGNORECASE)]
    price = nums[0] if nums else None
    qty   = nums[1] if len(nums) >= 2 else 1

    raw_name = re.sub(r'\b\d+\s*(?:штук[иа]?|шт\.?)?\b', '', text, flags=re.IGNORECASE)
    raw_name = re.sub(r'\s{2,}', ' ', raw_name).strip()

    canon = find_canon(raw_name, synonyms)
    return {
        "uid":      gen_uid(),
        "op":       op,
        "name":     canon or raw_name,
        "found":    canon is not None,
        "price":    price,
        "qty":      qty,
        "delivery": delivery,
    }

# ── Таблица ──────────────────────────────────────────────────────────────────

def write_op(sheets, d, site_data):
    today = datetime.now().strftime("%d.%m.%Y")
    uid   = d["uid"]
    op    = d["op"]
    name  = d["name"]
    qty   = d["qty"]
    price = d["price"] or site_data.get("price", 0)
    cost  = site_data.get("cost", 0)
    deliv = d["delivery"]

    all_rows = sheets["sklad"].get_all_values()
    next_row = len(all_rows) + 1

    if op == "Продажа":
        sheets["sklad"].append_row(
            [uid, today, "Продажа", deliv, name, 0, qty,
             f"=SUM(F$2:F{next_row})-SUM(G$2:G{next_row})"],
            value_input_option="USER_ENTERED")
    else:
        sheets["sklad"].append_row(
            [uid, today, "Закуп", deliv, name, qty, 0,
             f"=SUM(F$2:F{next_row})-SUM(G$2:G{next_row})"],
            value_input_option="USER_ENTERED")

    turnover = price * qty
    profit   = (price - cost) * qty if cost else 0
    if op == "Продажа":
        sheets["finance"].append_row([uid, today, "Продажа", deliv, name, turnover, f"Прибыль: {profit}"])
    else:
        sheets["finance"].append_row([uid, today, "Закуп", deliv, name, -(price * qty), ""])

    net = ((price - cost) * qty) if (cost and op == "Продажа") else ""
    sheets["history"].append_row([uid, today, op, name, price, qty, deliv, "", net])

def delete_uid(sheets, slug, uid):
    hist = sheets["history"].get_all_values()
    row_num, op, name, qty = None, "", "", 1
    for i, row in enumerate(hist):
        if row and row[0] == uid:
            row_num = i + 1
            op   = row[2] if len(row) > 2 else ""
            name = row[3] if len(row) > 3 else ""
            qty  = int(row[5]) if len(row) > 5 and row[5].isdigit() else 1
            break
    if row_num is None:
        return False, "UID не найден"
    for sheet_key in ["sklad", "finance"]:
        for i, row in enumerate(sheets[sheet_key].get_all_values()):
            if row and row[0] == uid:
                sheets[sheet_key].delete_rows(i + 1)
                break
    sheets["history"].delete_rows(row_num)
    change = qty if op == "Продажа" else -qty
    api_update(slug, name, change)
    return True, name

# ── Handlers ─────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_chat.id
    ctx = get_ctx(context.bot_data, tg_id)
    if ctx:
        res = api_check_tg(ctx["slug"], tg_id)
        if res.get("success"):
            await update.message.reply_text(
                f"С возвращением! Магазин: {ctx['name']}",
                reply_markup=keyboard())
            return
    context.user_data.clear()
    context.user_data["step"] = "slug_enter"
    await update.message.reply_text("Добро пожаловать в REESTOR!\n\nВведите slug вашего магазина:")

async def cmd_settable(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_chat.id
    if tg_id != SUPERADMIN:
        await update.message.reply_text("Нет доступа.")
        return
    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text("Использование: /settable <slug> <spreadsheet_id>")
        return

    slug = args[0].strip().lower()
    sid  = args[1].strip()

    # Проверяем доступ к таблице
    try:
        sheets = get_sheets(sid)
    except Exception as e:
        await update.message.reply_text(f"Не удалось открыть таблицу: {e}")
        return

    # Заполняем ТОВАРЫ из каталога сайта автоматически
    try:
        catalog = api_catalog(slug)
        products = catalog.get("products", [])
        visible  = [p for p in products if not p.get("hidden")]
        if visible:
            goods_sheet = sheets["goods"]
            all_rows = goods_sheet.get_all_values()
            if len(all_rows) > 1:
                goods_sheet.delete_rows(2, len(all_rows))
            rows_to_add = [[p["name"], ""] for p in visible]
            goods_sheet.append_rows(rows_to_add, value_input_option="USER_ENTERED")
            log.info("Заполнено %d товаров для %s", len(rows_to_add), slug)
    except Exception as e:
        log.error("Заполнение ТОВАРЫ: %s", e)

    # Ищем ожидающего клиента
    waiting_id   = context.bot_data.get(f"pending_{slug}")
    waiting_name = context.bot_data.get(f"pending_name_{slug}", slug)

    # Привязываем на сайте
    api_bind(slug, waiting_id or 0, sid)

    if waiting_id:
        save_ctx(context.bot_data, waiting_id, slug, sid, waiting_name)
        context.bot_data.pop(f"pending_{slug}", None)
        context.bot_data.pop(f"pending_name_{slug}", None)
        try:
            await context.bot.send_message(
                chat_id=waiting_id,
                text=f"Ваш магазин {waiting_name} подключён! Можете вносить продажи.",
                reply_markup=keyboard())
        except Exception as e:
            log.error("Уведомление клиента: %s", e)

    goods_count = len([p for p in api_catalog(slug).get("products", []) if not p.get("hidden")])
    await update.message.reply_text(
        f"Таблица привязана к магазину {slug}.\n"
        f"Товаров добавлено в ТОВАРЫ: {goods_count}")

async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_chat.id
    if tg_id != SUPERADMIN:
        return
    waiting = [(k.replace("pending_", ""), v)
               for k, v in context.bot_data.items()
               if k.startswith("pending_") and not k.startswith("pending_name_")]
    if not waiting:
        await update.message.reply_text("Нет магазинов ожидающих таблицу.")
        return
    text = "Ожидают таблицу:\n\n"
    for slug, tg in waiting:
        text += f"- {slug} (tg: {tg})\n/settable {slug} <spreadsheet_id>\n\n"
    await update.message.reply_text(text)

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_chat.id
    text  = update.message.text.strip()
    step  = context.user_data.get("step")

    # Кнопки меню
    if text in ("📦 Остатки", "💰 Прибыль", "📋 История", "🗑 Удалить запись"):
        ctx = get_ctx(context.bot_data, tg_id)
        if not ctx:
            await update.message.reply_text("Введите /start для входа.")
            return
        if text == "📦 Остатки":
            await show_stock(update, ctx["slug"])
        elif text == "💰 Прибыль":
            await show_profit(update, get_sheets(ctx["sid"]))
        elif text == "📋 История":
            await show_history(update, get_sheets(ctx["sid"]))
        elif text == "🗑 Удалить запись":
            context.user_data["step"] = "del_uid"
            await update.message.reply_text("Введите UID операции:")
        return

    # Удаление
    if step == "del_uid":
        context.user_data.pop("step", None)
        ctx = get_ctx(context.bot_data, tg_id)
        if not ctx:
            await update.message.reply_text("Введите /start для входа.")
            return
        ok, msg = delete_uid(get_sheets(ctx["sid"]), ctx["slug"], text)
        await update.message.reply_text(f"Удалено: {msg}" if ok else f"Ошибка: {msg}")
        return

    # Ввод slug
    if step == "slug_enter":
        slug = text.strip().lower()
        res  = api_check_tg(slug, tg_id)
        if res.get("success"):
            sid  = res.get("spreadsheetId")
            name = res.get("shopName", slug)
            if sid:
                save_ctx(context.bot_data, tg_id, slug, sid, name)
                context.user_data.clear()
                await update.message.reply_text(
                    f"С возвращением! Магазин: {name}",
                    reply_markup=keyboard())
                return
        context.user_data["slug"] = slug
        context.user_data["step"] = "access_code"
        await update.message.reply_text("Введите код доступа (8 символов):")
        return

    if step == "access_code":
        context.user_data["ac"]   = text.strip()
        context.user_data["step"] = "verify_code"
        await update.message.reply_text("Введите код подтверждения (4 цифры):")
        return

    if step == "verify_code":
        slug = context.user_data.get("slug", "")
        ac   = context.user_data.get("ac", "")
        res  = api_check_access(slug, ac, text.strip())
        if not res.get("success"):
            context.user_data.clear()
            await update.message.reply_text(
                f"Ошибка: {res.get('error','неизвестно')}. Начните заново: /start")
            return
        name = res.get("shopName", slug)
        context.user_data.clear()
        context.bot_data[f"pending_{slug}"]      = tg_id
        context.bot_data[f"pending_name_{slug}"] = name
        if SUPERADMIN:
            try:
                await context.bot.send_message(
                    chat_id=SUPERADMIN,
                    text=(f"Новый магазин ждёт таблицу!\n\n"
                          f"Магазин: {name} ({slug})\n"
                          f"TG ID: {tg_id}\n\n"
                          f"Команда для привязки:\n"
                          f"/settable {slug} <spreadsheet_id>"))
            except Exception as e:
                log.error("Уведомление суперадмину: %s", e)
        await update.message.reply_text(
            "Авторизация прошла успешно!\n\n"
            "Администратор получил уведомление и скоро подключит вашу таблицу. "
            "Вы получите сообщение когда всё будет готово.")
        return

    # Продажа / закуп
    ctx = get_ctx(context.bot_data, tg_id)
    if not ctx:
        await update.message.reply_text("Введите /start для входа.")
        return

    slug   = ctx["slug"]
    sheets = get_sheets(ctx["sid"])
    parsed = parse_msg(text, sheets)

    if not parsed["name"]:
        await update.message.reply_text("Не распознал название товара.")
        return

    site = api_find(slug, parsed["name"])
    if not site.get("found"):
        await update.message.reply_text(
            f"Товар {parsed['name']} не найден на сайте.\n"
            f"Проверьте синонимы в листе ТОВАРЫ.")
        return

    parsed["name"] = site.get("productName", parsed["name"])
    if parsed["price"] is None:
        parsed["price"] = site.get("price", 0)

    qty    = parsed["qty"]
    op     = parsed["op"]
    change = -qty if op == "Продажа" else qty

    res_site = api_update(slug, parsed["name"], change)
    write_op(sheets, parsed, site)

    actual  = api_find(slug, parsed["name"])
    stock   = actual.get("currentStock", res_site.get("newStock", "?"))
    price   = parsed["price"]
    cost    = site.get("cost", 0)
    profit  = (price - cost) * qty if (cost and op == "Продажа") else None
    em      = "💰" if op == "Продажа" else "📥"

    msg = (f"{em} {op}: {parsed['name']}\n"
           f"Цена: {price} руб x {qty} шт\n")
    if parsed["delivery"]:
        msg += f"Поставка: {parsed['delivery']}\n"
    if op == "Продажа":
        msg += f"Оборот: {price*qty} руб\n"
        if profit is not None:
            msg += f"Прибыль: {profit} руб\n"
    msg += f"Остаток: {stock} шт"

    if not res_site.get("success"):
        msg += f"\nСайт не обновлён: {res_site.get('error','?')}"

    await update.message.reply_text(msg)

# ── Просмотр ─────────────────────────────────────────────────────────────────

async def show_stock(update, slug):
    try:
        d        = api_catalog(slug)
        products = d.get("products", [])
        cats     = {c["id"]: c["name"] for c in d.get("categories", [])}
        groups   = {}
        for p in products:
            if p.get("hidden"):
                continue
            cat = cats.get(p.get("categoryId", ""), "Другое")
            groups.setdefault(cat, []).append(
                f"- {p['name']} — {p['stock']} шт | {p.get('price',0)} руб")
        if not groups:
            await update.message.reply_text("Склад пуст")
            return
        text = "ОСТАТКИ:\n"
        for cat, rows in sorted(groups.items()):
            text += f"\n{cat}\n" + "\n".join(rows) + "\n"
        await update.message.reply_text(text)
    except Exception as e:
        log.error("show_stock: %s", e)
        await update.message.reply_text("Не удалось загрузить остатки")

async def show_profit(update, sheets):
    try:
        rows  = sheets["finance"].get_all_values()
        total = 0.0
        for row in rows[1:]:
            if len(row) > 5 and row[5]:
                try:
                    total += float(row[5])
                except ValueError:
                    pass
        await update.message.reply_text(f"Баланс: {total:,.0f} руб")
    except Exception as e:
        log.error("show_profit: %s", e)
        await update.message.reply_text("Не удалось получить данные")

async def show_history(update, sheets):
    try:
        all_rows = sheets["history"].get_all_values()
        data     = [r for r in all_rows[1:] if r and r[0]]
        last10   = data[-10:]
        if not last10:
            await update.message.reply_text("История пуста")
            return
        text = "Последние операции:\n\n"
        for row in reversed(last10):
            uid  = row[0]
            date = row[1] if len(row) > 1 else "?"
            op   = row[2] if len(row) > 2 else "?"
            name = row[3] if len(row) > 3 else "?"
            pr   = row[4] if len(row) > 4 else "?"
            qty  = row[5] if len(row) > 5 else "?"
            text += f"{uid}\n{date} — {op}: {name}, {pr}р x {qty}шт\n\n"
        text += "Для удаления: кнопка Удалить запись -> UID"
        await update.message.reply_text(text)
    except Exception as e:
        log.error("show_history: %s", e)
        await update.message.reply_text("Не удалось загрузить историю")

# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("REESTOR Multi запускается")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("settable", cmd_settable))
    app.add_handler(CommandHandler("pending",  cmd_pending))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    app.run_polling()
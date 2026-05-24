"""
REESTOR — мультимагазинный бот
Один бот обслуживает 50+ магазинов.
Каждый магазин получает свою Google таблицу автоматически.
Привязка telegramId → shopSlug → spreadsheetId хранится на сайте.
"""

import os, re, json, time, random, logging
import requests
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import gspread
from oauth2client.service_account import ServiceAccountCredentials
# googleapiclient не используется

# ─────────────────────────────────────────────
# Логирование
# ─────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
лог = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Конфигурация
# ─────────────────────────────────────────────
ТОКЕН       = os.environ["TELEGRAM_TOKEN"]
GOOGLE_KEY  = json.loads(os.environ["GDRIVE_CREDENTIALS"])
САЙТ        = os.environ.get("SITE_URL", "https://b2bshopb2b.up.railway.app") + "/api/admin"

_SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

# ─────────────────────────────────────────────
# Google авторизация (одна на весь бот)
# ─────────────────────────────────────────────
_крред = ServiceAccountCredentials.from_json_keyfile_dict(GOOGLE_KEY, _SCOPE)
гс     = gspread.authorize(_крред)

# ─────────────────────────────────────────────
# Кэш подключений к таблицам  { spreadsheetId: {лист_склад, ...} }
# ─────────────────────────────────────────────
_кэш_листов: dict = {}

def получить_листы(spreadsheet_id: str) -> dict:
    """Возвращает кэшированные листы таблицы."""
    if spreadsheet_id in _кэш_листов:
        return _кэш_листов[spreadsheet_id]
    кн = гс.open_by_key(spreadsheet_id)
    листы = {
        "склад":   кн.worksheet("СКЛАД"),
        "финансы": кн.worksheet("ФИНАНСЫ"),
        "история": кн.worksheet("ИСТОРИЯ"),
        "товары":  кн.worksheet("ТОВАРЫ"),
    }
    _кэш_листов[spreadsheet_id] = листы
    лог.info("Подключились к таблице %s", spreadsheet_id)
    return листы

# ─────────────────────────────────────────────
# Создание новой таблицы для магазина
# ─────────────────────────────────────────────
def создать_таблицу(shop_name: str) -> str:
    """
    Копирует шаблон таблицы и возвращает spreadsheetId новой таблицы.
    Копирование работает без Drive квоты сервисного аккаунта —
    файл создаётся на Drive владельца шаблона (твоём личном).
    """
    ШАБЛОН_ID   = "1visnPEAgMm3A22eXl8mCn2Pkunr7N6afoTj1st5pmQI"
    OWNER_EMAIL = os.environ.get("OWNER_EMAIL", "")

    # Копируем шаблон через gspread — файл появится на Drive владельца шаблона
    кн_шаблон = гс.open_by_key(ШАБЛОН_ID)
    новая_кн  = кн_шаблон.copy(title=f"REESTOR — {shop_name}")
    sid = новая_кн.id
    лог.info("Скопирована таблица %s для '%s'", sid, shop_name)

    # Расшариваем владельцу если задан email
    if OWNER_EMAIL:
        try:
            новая_кн.share(OWNER_EMAIL, perm_type="user", role="writer")
            лог.info("Таблица расшарена на %s", OWNER_EMAIL)
        except Exception as e:
            лог.warning("Не удалось расшарить: %s", e)

    # Открываем листы
    склад   = новая_кн.worksheet("СКЛАД")
    финансы = новая_кн.worksheet("ФИНАНСЫ")
    история = новая_кн.worksheet("ИСТОРИЯ")
    товары  = новая_кн.worksheet("ТОВАРЫ")

    # Кэшируем
    _кэш_листов[sid] = {
        "склад":   склад,
        "финансы": финансы,
        "история": история,
        "товары":  товары,
    }

    лог.info("Таблица %s готова для '%s'", sid, shop_name)
    return sid

# ─────────────────────────────────────────────
# Вспомогательные функции
# ─────────────────────────────────────────────
def генерировать_uid() -> str:
    return f"{int(time.time()*1000)}_{random.randint(1000,9999)}"

def клавиатура() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([
        [KeyboardButton("📦 Остатки"), KeyboardButton("💰 Прибыль")],
        [KeyboardButton("📋 История"), KeyboardButton("🗑 Удалить запись")],
    ], resize_keyboard=True)

# ─────────────────────────────────────────────
# API сайта
# ─────────────────────────────────────────────
def апи_проверить_telegram(telegram_id: int) -> dict:
    """Проверяет привязку и возвращает shopSlug + spreadsheetId."""
    # Нам нужно перебрать все магазины — но мы не знаем slug по telegramId.
    # Поэтому check-telegram принимает telegramId без slug — нужен новый эндпоинт,
    # ИЛИ бот сохраняет slug в context.user_data после первой привязки.
    # Используем хранилище бота (context.bot_data) как быстрый кэш:
    return {}  # заглушка — реальная логика ниже через bot_data

def апи_check_telegram(slug: str, telegram_id: int) -> dict:
    try:
        r = requests.get(f"{САЙТ}/check-telegram",
                         params={"slug": slug, "telegramId": telegram_id}, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        лог.error("check-telegram: %s", e)
    return {"success": False}

def апи_check_bot_access(slug: str, access_code: str, verify_code: str) -> dict:
    try:
        r = requests.get(f"{САЙТ}/check-bot-access",
                         params={"slug": slug, "accessCode": access_code, "verifyCode": verify_code},
                         timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        лог.error("check-bot-access: %s", e)
    return {"success": False, "error": "network_error"}

def апи_bind_telegram(slug: str, telegram_id: int, spreadsheet_id: str) -> dict:
    try:
        r = requests.post(f"{САЙТ}/bind-telegram",
                          json={"shopSlug": slug, "telegramId": telegram_id,
                                "spreadsheetId": spreadsheet_id},
                          headers={"Content-Type": "application/json"}, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        лог.error("bind-telegram: %s", e)
    return {"success": False}

def апи_найти_товар(slug: str, название: str) -> dict:
    try:
        r = requests.get(f"{САЙТ}/find-product",
                         params={"shopSlug": slug, "productName": название}, timeout=10)
        if r.status_code == 200:
            д = r.json()
            if д.get("found"):
                return д
    except Exception as e:
        лог.error("find-product: %s", e)
    return {"found": False}

def апи_обновить_остаток(slug: str, название: str, изменение: int) -> dict:
    тело = {"shopSlug": slug, "productName": название, "quantityChange": изменение}
    try:
        r = requests.post(f"{САЙТ}/update-stock",
                          data=json.dumps(тело, ensure_ascii=False).encode("utf-8"),
                          headers={"Content-Type": "application/json; charset=utf-8"},
                          timeout=10)
        if r.status_code == 200:
            return r.json()
        return {"success": False, "error": f"http_{r.status_code}"}
    except Exception as e:
        лог.error("update-stock: %s", e)
        return {"success": False, "error": str(e)}

def апи_каталог_магазина(slug: str) -> dict:
    try:
        r = requests.get(
            f"{os.environ.get('SITE_URL','https://b2bshopb2b.up.railway.app')}/api/shop/{slug}",
            timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        лог.error("catalog: %s", e)
    return {}

# ─────────────────────────────────────────────
# Контекст магазина из bot_data
# ─────────────────────────────────────────────
def получить_контекст(bot_data: dict, telegram_id: int) -> dict | None:
    """Возвращает {slug, spreadsheetId, shopName} или None."""
    return bot_data.get(f"shop_{telegram_id}")

def сохранить_контекст(bot_data: dict, telegram_id: int, slug: str,
                        spreadsheet_id: str, shop_name: str):
    bot_data[f"shop_{telegram_id}"] = {
        "slug":          slug,
        "spreadsheetId": spreadsheet_id,
        "shopName":      shop_name,
    }

# ─────────────────────────────────────────────
# Парсинг сообщения
# ─────────────────────────────────────────────
def загрузить_синонимы(листы: dict) -> dict:
    результат: dict = {}
    try:
        строки = листы["товары"].get_all_values()
        for стр in строки[1:]:
            if not стр or not стр[0].strip():
                continue
            канон = стр[0].strip()
            результат[канон.lower()] = канон
            if len(стр) > 1 and стр[1].strip():
                for с in стр[1].split(","):
                    с = с.strip()
                    if с:
                        результат[с.lower()] = канон
    except Exception as e:
        лог.error("загрузить_синонимы: %s", e)
    return результат

def найти_канон(текст: str, синонимы: dict) -> str | None:
    тл = текст.lower().strip()
    if тл in синонимы:
        return синонимы[тл]
    лучший, лучшая_длина = None, 0
    for синоним, канон in синонимы.items():
        if синоним in тл and len(синоним) > лучшая_длина:
            лучший, лучшая_длина = канон, len(синоним)
    return лучший

def разобрать_сообщение(текст: str, листы: dict) -> dict:
    синонимы = загрузить_синонимы(листы)
    текст = текст.strip()
    операция = "Продажа"
    if текст.lower().startswith("закуп"):
        операция = "Закуп"
        текст = текст[5:].strip()

    поставка = None
    м = re.search(r'поставка\s+(\d+)', текст, re.IGNORECASE)
    if м:
        поставка = int(м.group(1))
        текст = текст[:м.start()].strip()

    числа = [int(м2.group(1)) for м2 in
              re.finditer(r'\b(\d+)\s*(?:штук[иа]?|шт\.?)?\b', текст, re.IGNORECASE)]
    цена       = числа[0] if числа else None
    количество = числа[1] if len(числа) >= 2 else 1

    название_сырое = re.sub(r'\b\d+\s*(?:штук[иа]?|шт\.?)?\b', '', текст, flags=re.IGNORECASE)
    название_сырое = re.sub(r'\s{2,}', ' ', название_сырое).strip()

    канон = найти_канон(название_сырое, синонимы)

    return {
        "uid":          генерировать_uid(),
        "операция":     операция,
        "товар":        канон or название_сырое,
        "канон_найден": канон is not None,
        "цена":         цена,
        "количество":   количество,
        "поставка":     поставка,
    }

# ─────────────────────────────────────────────
# Запись в Google Sheets
# ─────────────────────────────────────────────
def записать_операцию(листы: dict, д: dict, сайт_данные: dict):
    сег  = datetime.now().strftime("%d.%m.%Y")
    uid  = д["uid"]
    опер = д["операция"]
    тов  = д["товар"]
    кол  = д["количество"]
    цена = д["цена"] or сайт_данные.get("price", 0)
    себ  = сайт_данные.get("cost", 0)
    пост = д["поставка"]

    все = листы["склад"].get_all_values()
    след = len(все) + 1

    if опер == "Продажа":
        строка_склад = [uid, сег, "Продажа", пост, тов, 0, кол,
                        f"=SUM(F$2:F{след})-SUM(G$2:G{след})"]
    else:
        строка_склад = [uid, сег, "Закуп", пост, тов, кол, 0,
                        f"=SUM(F$2:F{след})-SUM(G$2:G{след})"]

    листы["склад"].append_row(строка_склад, value_input_option="USER_ENTERED")

    оборот = цена * кол
    приб   = (цена - себ) * кол if себ else 0
    if опер == "Продажа":
        листы["финансы"].append_row([uid, сег, "Продажа", пост, тов, оборот, f"Прибыль: {приб}"])
    else:
        листы["финансы"].append_row([uid, сег, "Закуп", пост, тов, -(цена * кол), ""])

    чистая = ((цена - себ) * кол) if (себ and опер == "Продажа") else ""
    листы["история"].append_row([uid, сег, опер, тов, цена, кол, пост, "", чистая])

def удалить_по_uid(листы: dict, slug: str, uid: str) -> tuple[bool, str]:
    ист = листы["история"].get_all_values()
    номер, инфо_оп, инфо_тов, инфо_кол = None, "", "", 1
    for i, стр in enumerate(ист):
        if стр and стр[0] == uid:
            номер    = i + 1
            инфо_оп  = стр[2] if len(стр) > 2 else ""
            инфо_тов = стр[3] if len(стр) > 3 else ""
            инфо_кол = int(стр[5]) if len(стр) > 5 and стр[5].isdigit() else 1
            break
    if номер is None:
        return False, "UID не найден"

    for л in ["склад", "финансы"]:
        for i, стр in enumerate(листы[л].get_all_values()):
            if стр and стр[0] == uid:
                листы[л].delete_rows(i + 1)
                break
    листы["история"].delete_rows(номер)

    изм = инфо_кол if инфо_оп == "Продажа" else -инфо_кол
    апи_обновить_остаток(slug, инфо_тов, изм)
    return True, инфо_тов

# ─────────────────────────────────────────────
# Обработчики Telegram
# ─────────────────────────────────────────────
async def cmd_старт(update: Update, context: ContextTypes.DEFAULT_TYPE):
    чат = update.effective_chat.id

    # 1. Проверяем кэш бота (быстро)
    кнт = получить_контекст(context.bot_data, чат)
    if кнт:
        рез = апи_check_telegram(кнт["slug"], чат)
        if рез.get("success"):
            await update.message.reply_text(
                f"👋 С возвращением! Магазин: *{кнт['shopName']}*",
                parse_mode="Markdown", reply_markup=клавиатура())
            return

    # 2. Кэш пуст (рестарт бота) — просим slug чтобы восстановить сессию
    context.user_data.clear()
    context.user_data["шаг"] = "slug_restore"
    await update.message.reply_text(
        "👋 Введите *slug* вашего магазина для входа:",
        parse_mode="Markdown")

async def обработать_сообщение(update: Update, context: ContextTypes.DEFAULT_TYPE):
    чат   = update.effective_chat.id
    текст = update.message.text.strip()
    шаг   = context.user_data.get("шаг")

    # ── Кнопки меню ──────────────────────────────────────────────────────────
    if текст in ("📦 Остатки", "💰 Прибыль", "📋 История", "🗑 Удалить запись"):
        кнт = получить_контекст(context.bot_data, чат)
        if not кнт:
            await update.message.reply_text("❌ Сначала войдите: /start")
            return
        if текст == "📦 Остатки":
            await показать_остатки(update, кнт["slug"])
        elif текст == "💰 Прибыль":
            await показать_прибыль(update, получить_листы(кнт["spreadsheetId"]))
        elif текст == "📋 История":
            await показать_историю(update, получить_листы(кнт["spreadsheetId"]))
        elif текст == "🗑 Удалить запись":
            context.user_data["шаг"] = "del_uid"
            await update.message.reply_text("Введите UID операции:")
        return

    # ── Удаление ──────────────────────────────────────────────────────────────
    if шаг == "del_uid":
        context.user_data.pop("шаг", None)
        кнт = получить_контекст(context.bot_data, чат)
        if not кнт:
            await update.message.reply_text("❌ Сначала войдите: /start")
            return
        успех, сообщение = удалить_по_uid(
            получить_листы(кнт["spreadsheetId"]), кнт["slug"], текст)
        await update.message.reply_text(
            f"✅ Удалено: {сообщение}" if успех else f"❌ {сообщение}")
        return

    # ── Восстановление сессии после рестарта ────────────────────────────────
    if шаг == "slug_restore":
        slug = текст.strip().lower()
        рез = апи_check_telegram(slug, чат)
        if рез.get("success"):
            sid       = рез.get("spreadsheetId")
            shop_name = рез.get("shopName", slug)
            if sid:
                сохранить_контекст(context.bot_data, чат, slug, sid, shop_name)
                context.user_data.clear()
                await update.message.reply_text(
                    f"✅ С возвращением! Магазин: *{shop_name}*",
                    parse_mode="Markdown", reply_markup=клавиатура())
            else:
                # Магазин привязан но таблицы нет — создаём
                await update.message.reply_text("⏳ Восстанавливаю таблицу...")
                try:
                    sid = создать_таблицу(shop_name)
                    апи_bind_telegram(slug, чат, sid)
                    сохранить_контекст(context.bot_data, чат, slug, sid, shop_name)
                    context.user_data.clear()
                    await update.message.reply_text(
                        f"✅ Готово! Магазин: *{shop_name}*",
                        parse_mode="Markdown", reply_markup=клавиатура())
                except Exception as e:
                    await update.message.reply_text(f"❌ Ошибка: {e}")
        else:
            # Не привязан — начинаем полную авторизацию
            context.user_data["slug"] = slug
            context.user_data["шаг"] = "access_code"
            await update.message.reply_text("🔑 Введите код доступа (8 символов):")
        return

    # ── Авторизация ──────────────────────────────────────────────────────────
    if шаг == "slug":
        context.user_data["slug"] = текст.strip().lower()
        context.user_data["шаг"]  = "access_code"
        await update.message.reply_text("🔑 Введите код доступа (8 символов):")
        return

    if шаг == "access_code":
        context.user_data["ac"]  = текст.strip()
        context.user_data["шаг"] = "verify_code"
        await update.message.reply_text("🔢 Введите код подтверждения (4 цифры):")
        return

    if шаг == "verify_code":
        slug = context.user_data.get("slug", "")
        ac   = context.user_data.get("ac", "")
        vc   = текст.strip()

        рез = апи_check_bot_access(slug, ac, vc)
        if not рез.get("success"):
            context.user_data.clear()
            await update.message.reply_text(
                f"❌ Ошибка: {рез.get('error','неизвестно')}. Начните заново: /start")
            return

        shop_name = рез.get("shopName", slug)
        await update.message.reply_text("⏳ Создаю таблицу для вашего магазина...")

        try:
            sid = создать_таблицу(shop_name)
        except Exception as e:
            лог.error("создать_таблицу: %s", e)
            await update.message.reply_text(f"❌ Ошибка создания таблицы: {e}")
            return

        привязка = апи_bind_telegram(slug, чат, sid)
        if not привязка.get("success"):
            await update.message.reply_text("⚠️ Таблица создана, но не удалось привязать к сайту.")
            return

        сохранить_контекст(context.bot_data, чат, slug, sid, shop_name)
        context.user_data.clear()

        await update.message.reply_text(
            f"✅ Готово! Магазин *{shop_name}* подключён.\n"
            f"📊 Ваша таблица создана автоматически.\n\n"
            f"Заполните лист *ТОВАРЫ* — добавьте названия товаров и синонимы.\n"
            f"После этого можно вносить продажи!",
            parse_mode="Markdown", reply_markup=клавиатура())
        return

    # ── Повторный вход (уже привязан, но нет в кэше) ─────────────────────────
    if шаг is None:
        кнт = получить_контекст(context.bot_data, чат)
        if not кнт:
            # Может быть бот перезапустился — попробуем восстановить через сайт
            # Не знаем slug — просим заново
            await update.message.reply_text(
                "Введите /start для начала работы.")
            return

        # ── Основная логика: продажа / закуп ─────────────────────────────────
        slug = кнт["slug"]
        листы = получить_листы(кнт["spreadsheetId"])
        данные = разобрать_сообщение(текст, листы)

        if not данные["товар"]:
            await update.message.reply_text("❌ Не распознал название товара.")
            return

        сайт = апи_найти_товар(slug, данные["товар"])
        if not сайт.get("found"):
            await update.message.reply_text(
                f"❌ Товар «{данные['товар']}» не найден на сайте.\n"
                f"Проверьте синонимы в листе ТОВАРЫ.")
            return

        данные["товар"] = сайт.get("productName", данные["товар"])
        if данные["цена"] is None:
            данные["цена"] = сайт.get("price", 0)

        кол  = данные["количество"]
        опер = данные["операция"]
        изм  = -кол if опер == "Продажа" else кол

        рез_сайт = апи_обновить_остаток(slug, данные["товар"], изм)
        записать_операцию(листы, данные, сайт)

        актуал  = апи_найти_товар(slug, данные["товар"])
        остаток = актуал.get("currentStock", рез_сайт.get("newStock", "?"))

        цена  = данные["цена"]
        себ   = сайт.get("cost", 0)
        приб  = (цена - себ) * кол if (себ and опер == "Продажа") else None
        эм    = "💰" if опер == "Продажа" else "📥"

        ответ = (f"{эм} *{опер}*: {данные['товар']}\n"
                 f"💵 {цена} руб × {кол} шт\n")
        if данные["поставка"]:
            ответ += f"📋 Поставка: {данные['поставка']}\n"
        if опер == "Продажа":
            ответ += f"🛒 Оборот: {цена*кол} руб\n"
            if приб is not None:
                ответ += f"🟢 Прибыль: {приб} руб\n"
        ответ += f"📦 Остаток: {остаток} шт"

        if not рез_сайт.get("success"):
            ответ += f"\n⚠️ Сайт не обновлён: {рез_сайт.get('error','?')}"

        await update.message.reply_text(ответ, parse_mode="Markdown")

# ─────────────────────────────────────────────
# Просмотровые функции
# ─────────────────────────────────────────────
async def показать_остатки(update: Update, slug: str):
    try:
        д      = апи_каталог_магазина(slug)
        товары = д.get("products", [])
        кат    = {к["id"]: к["name"] for к in д.get("categories", [])}
        группы: dict = {}
        for т in товары:
            if т.get("hidden"):
                continue
            заг = кат.get(т.get("categoryId",""), "Другое")
            назв = т["name"]
            группы.setdefault(заг, []).append(
                f"• {назв} — {т['stock']} шт | {т.get('price',0)} руб")
        if not группы:
            await update.message.reply_text("📦 Склад пуст")
            return
        ответ = "📦 *ОСТАТКИ:*\n"
        for заг, стр in sorted(группы.items()):
            ответ += f"\n📌 {заг}\n" + "\n".join(стр) + "\n"
        await update.message.reply_text(ответ, parse_mode="Markdown")
    except Exception as e:
        лог.error("показать_остатки: %s", e)
        await update.message.reply_text("⚠️ Не удалось загрузить остатки")

async def показать_прибыль(update: Update, листы: dict):
    try:
        строки = листы["финансы"].get_all_values()
        итог = sum(float(стр[5]) for стр in строки[1:] if len(стр)>5 and стр[5]
                   and стр[5].replace(".","").replace("-","").isdigit())
        await update.message.reply_text(f"💸 Баланс: {итог:,.0f} руб")
    except Exception as e:
        лог.error("показать_прибыль: %s", e)
        await update.message.reply_text("⚠️ Не удалось получить данные")

async def показать_историю(update: Update, листы: dict):
    try:
        все   = листы["история"].get_all_values()
        данные = [с for с in все[1:] if с and с[0]]
        посл  = данные[-10:]
        if not посл:
            await update.message.reply_text("📋 История пуста")
            return
        ответ = "📋 *Последние операции:*\n\n"
        for стр in reversed(посл):
            uid  = стр[0]
            дата = стр[1] if len(стр)>1 else "?"
            опер = стр[2] if len(стр)>2 else "?"
            тов  = стр[3] if len(стр)>3 else "?"
            цена = стр[4] if len(стр)>4 else "?"
            кол  = стр[5] if len(стр)>5 else "?"
            ответ += f"`{uid}`\n{дата} — {опер}: {тов}, {цена}р × {кол}шт\n\n"
        ответ += "🗑 Удалить: кнопка *«Удалить запись»* → UID"
        await update.message.reply_text(ответ, parse_mode="Markdown")
    except Exception as e:
        лог.error("показать_историю: %s", e)
        await update.message.reply_text("⚠️ Не удалось загрузить историю")

# ─────────────────────────────────────────────
# Точка входа
# ─────────────────────────────────────────────
if __name__ == "__main__":
    лог.info("🚀 REESTOR Multi запускается")
    app = ApplicationBuilder().token(ТОКЕН).build()
    app.add_handler(CommandHandler("start",   cmd_старт))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, обработать_сообщение))
    app.run_polling()

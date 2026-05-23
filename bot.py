"""
REESTOR — бот учёта продаж
Переписан с нуля. Все проблемы исходной версии устранены.
"""

import os
import json
import time
import random
import logging
import requests
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ─────────────────────────────────────────────
# Логирование
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
лог = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Конфигурация из переменных окружения
# ─────────────────────────────────────────────
ТОКЕН      = os.environ["TELEGRAM_TOKEN"]
ТАБЛИЦА_ID = os.environ["SPREADSHEET_ID"]
GOOGLE_KEY = json.loads(os.environ["GDRIVE_CREDENTIALS"])
SLUG       = os.environ.get("SHOP_SLUG", "shop")

САЙТ     = "https://b2bshopb2b.up.railway.app/api/admin"
МАГАЗИН  = f"https://b2bshopb2b.up.railway.app/api/shop/{SLUG}"

# ─────────────────────────────────────────────
# Google Sheets
# ─────────────────────────────────────────────
_scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
_крред = ServiceAccountCredentials.from_json_keyfile_dict(GOOGLE_KEY, _scope)
гс     = gspread.authorize(_крред)
кн     = гс.open_by_key(ТАБЛИЦА_ID)

лист_склад   = кн.worksheet("СКЛАД")
лист_финансы = кн.worksheet("ФИНАНСЫ")
лист_история = кн.worksheet("ИСТОРИЯ")
лист_товары  = кн.worksheet("ТОВАРЫ")

# ─────────────────────────────────────────────
# Вспомогательные функции
# ─────────────────────────────────────────────

def генерировать_uid() -> str:
    """Уникальный ID операции: метка времени + случайное число."""
    return f"{int(time.time() * 1000)}_{random.randint(1000, 9999)}"


def клавиатура() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([
        [KeyboardButton("📦 Остатки"), KeyboardButton("💰 Прибыль")],
        [KeyboardButton("📋 История"), KeyboardButton("🗑 Удалить запись")]
    ], resize_keyboard=True)


def загрузить_синонимы() -> dict:
    """Словарь: синоним.lower() → каноническое название."""
    результат: dict = {}
    try:
        строки = лист_товары.get_all_values()
        for стр in строки[1:]:
            if not стр or not стр[0].strip():
                continue
            канон = стр[0].strip()
            результат[канон.lower()] = канон
            if len(стр) > 1 and стр[1].strip():
                for синоним in стр[1].split(","):
                    с = синоним.strip()
                    if с:
                        результат[с.lower()] = канон
    except Exception as e:
        лог.error("Ошибка загрузки синонимов: %s", e)
    return результат


def разрешить_название(сырое: str, синонимы: dict) -> str:
    """Вернуть каноническое название или исходную строку."""
    return синонимы.get(сырое.lower(), сырое)

# ─────────────────────────────────────────────
# API сайта
# ─────────────────────────────────────────────

def апи_найти_товар(название: str) -> dict:
    """Найти товар через /find-product, при неудаче — через /shop/{slug}."""
    # Попытка 1: прямой поиск
    try:
        url = f"{САЙТ}/find-product"
        params = {"shopSlug": SLUG, "productName": название}
        лог.info("find-product → %s %s", url, params)
        r = requests.get(url, params=params, timeout=10)
        лог.info("find-product ← %d %s", r.status_code, r.text[:200])
        if r.status_code == 200:
            д = r.json()
            if д.get("found"):
                return д
    except Exception as e:
        лог.error("find-product exception: %s", e)

    # Попытка 2: перебор по каталогу магазина
    try:
        лог.info("shop fallback → %s", МАГАЗИН)
        r = requests.get(МАГАЗИН, timeout=10)
        лог.info("shop fallback ← %d", r.status_code)
        if r.status_code == 200:
            для_сравн = название.lower()
            for т in r.json().get("products", []):
                if для_сравн in т["name"].lower() or т["name"].lower() in для_сравн:
                    лог.info("Совпадение по каталогу: %s", т["name"])
                    return {
                        "found": True,
                        "productId": т.get("id", ""),
                        "productName": т["name"],
                        "price": т.get("price", 0),
                        "cost": т.get("cost", 0),
                        "currentStock": т.get("stock", 0)
                    }
    except Exception as e:
        лог.error("shop fallback exception: %s", e)

    return {"found": False}


def апи_обновить_остаток(название: str, изменение: int) -> dict:
    """POST /update-stock. Возвращает ответ API."""
    тело = {"shopSlug": SLUG, "productName": название, "quantityChange": изменение}
    лог.info("update-stock → %s", тело)
    try:
        r = requests.post(
            f"{САЙТ}/update-stock",
            json=тело,
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=10
        )
        лог.info("update-stock ← %d %s", r.status_code, r.text[:200])
        if r.status_code == 200:
            return r.json()
        return {"success": False, "error": f"http_{r.status_code}"}
    except Exception as e:
        лог.error("update-stock exception: %s", e)
        return {"success": False, "error": str(e)}


def апи_проверить_telegram(telegram_id: int) -> dict:
    """GET /check-telegram."""
    try:
        r = requests.get(
            f"{САЙТ}/check-telegram",
            params={"slug": SLUG, "telegramId": telegram_id},
            timeout=10
        )
        лог.info("check-telegram ← %d %s", r.status_code, r.text[:200])
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        лог.error("check-telegram exception: %s", e)
    return {"success": False}


def апи_проверить_доступ(slug: str, access_code: str, verify_code: str) -> dict:
    """GET /check-bot-access."""
    try:
        r = requests.get(
            f"{САЙТ}/check-bot-access",
            params={"slug": slug, "accessCode": access_code, "verifyCode": verify_code},
            timeout=10
        )
        лог.info("check-bot-access ← %d %s", r.status_code, r.text[:200])
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        лог.error("check-bot-access exception: %s", e)
    return {"success": False, "error": "network_error"}


def апи_привязать_telegram(slug: str, telegram_id: int) -> dict:
    """POST /bind-telegram."""
    try:
        r = requests.post(
            f"{САЙТ}/bind-telegram",
            json={"shopSlug": slug, "telegramId": telegram_id},
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=10
        )
        лог.info("bind-telegram ← %d %s", r.status_code, r.text[:200])
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        лог.error("bind-telegram exception: %s", e)
    return {"success": False}

# ─────────────────────────────────────────────
# Парсинг сообщения о продаже/закупе
# ─────────────────────────────────────────────

def разобрать_сообщение(текст: str) -> dict:
    """
    Формат (регистр не важен):
      [закуп] <название> <цена> [<кол>шт] [поставка <N>]

    Числа: первое — цена, второе — количество.
    Слова-маркеры количества: «шт», «штук», «штуки».
    """
    синонимы = загрузить_синонимы()
    текст = текст.strip()

    операция = "Продажа"
    тл = текст.lower()
    if тл.startswith("закуп"):
        операция = "Закуп"
        текст = текст[5:].strip()

    # Поставка
    поставка = None
    if "поставка" in текст.lower():
        ч = текст.lower().split("поставка")
        текст = текст[:len(ч[0])].strip()  # до слова "поставка"
        хвост = ч[1].strip().split()
        if хвост and хвост[0].isdigit():
            поставка = int(хвост[0])

    # Разбор токенов
    слова = текст.split()
    числа: list[int] = []
    товар_слова: list[str] = []
    пропустить_следующее = False

    for i, сл in enumerate(слова):
        if пропустить_следующее:
            пропустить_следующее = False
            continue
        # «500шт», «2шт»
        чистое = сл.lower().rstrip("шт").rstrip("штук").rstrip("штуки")
        if чистое.isdigit():
            числа.append(int(чистое))
        elif сл.lower() in ("шт", "штук", "штуки"):
            # маркер — пропускаем, число уже добавлено из предыдущего токена
            pass
        else:
            товар_слова.append(сл)

    # Первое число — цена, второе — количество
    цена = числа[0] if числа else None
    количество = числа[1] if len(числа) > 1 else 1

    товар = " ".join(товар_слова).strip()
    товар = разрешить_название(товар, синонимы)

    return {
        "uid":        генерировать_uid(),
        "операция":   операция,
        "товар":      товар,
        "цена":       цена,
        "количество": количество,
        "поставка":   поставка,
        "клиент":     None,
    }

# ─────────────────────────────────────────────
# Запись в Google Sheets
# ─────────────────────────────────────────────

def записать_операцию(д: dict, сайт_данные: dict) -> None:
    """
    Записывает операцию в СКЛАД, ФИНАНСЫ, ИСТОРИЯ.
    Первый столбец каждого листа — UID (кроме ТОВАРЫ).

    Структура СКЛАД:  UID | Дата | Операция | Поставка | Товар | Приход | Расход | Остаток
    Структура ФИНАНСЫ: UID | Дата | Операция | Поставка | Товар | Сумма  | Комментарий
    Структура ИСТОРИЯ: UID | Дата | Операция | Товар    | Цена  | Кол-во | Поставка | Клиент | Прибыль
    """
    сег  = datetime.now().strftime("%d.%m.%Y")
    uid  = д["uid"]
    опер = д["операция"]
    тов  = д["товар"]
    кол  = д["количество"]
    цена = д["цена"] or сайт_данные.get("price", 0)
    себ  = сайт_данные.get("cost", 0)
    пост = д["поставка"]
    кл   = д.get("клиент") or ""

    # СКЛАД
    if опер == "Продажа":
        лист_склад.append_row([uid, сег, "Продажа", пост, тов, 0, кол, ""])
    else:
        лист_склад.append_row([uid, сег, "Закуп", пост, тов, кол, 0, ""])

    # ФИНАНСЫ
    if опер == "Продажа":
        оборот = цена * кол
        приб   = (цена - себ) * кол if себ else 0
        лист_финансы.append_row([uid, сег, "Продажа", пост, тов, оборот, f"Прибыль: {приб}"])
    else:
        лист_финансы.append_row([uid, сег, "Закуп", пост, тов, -(цена * кол), ""])

    # ИСТОРИЯ
    чистая = ((цена - себ) * кол) if (себ and опер == "Продажа") else ""
    лист_история.append_row([uid, сег, опер, тов, цена, кол, пост, кл, чистая])


def удалить_по_uid(uid: str) -> tuple[bool, str]:
    """
    Удаляет строку с данным UID из ИСТОРИИ, СКЛАДА и ФИНАНСОВ.
    Возвращает (успех, название_товара / сообщение_об_ошибке).
    """
    # ── ИСТОРИЯ ──
    ист_данные = лист_история.get_all_values()
    номер_строки_ист = None
    инфо_операция = ""
    инфо_товар = ""
    инфо_кол = 1

    for i, стр in enumerate(ист_данные):
        if стр and стр[0] == uid:
            номер_строки_ист = i + 1  # 1-based
            инфо_операция = стр[2] if len(стр) > 2 else ""
            инфо_товар    = стр[3] if len(стр) > 3 else ""
            инфо_кол      = int(стр[5]) if len(стр) > 5 and стр[5].isdigit() else 1
            break

    if номер_строки_ист is None:
        return False, "UID не найден в ИСТОРИИ"

    # ── СКЛАД ──
    скл_данные = лист_склад.get_all_values()
    for i, стр in enumerate(скл_данные):
        if стр and стр[0] == uid:
            лист_склад.delete_rows(i + 1)
            лог.info("Удалена строка из СКЛАДА: row %d", i + 1)
            break

    # ── ФИНАНСЫ ──
    фин_данные = лист_финансы.get_all_values()
    for i, стр in enumerate(фин_данные):
        if стр and стр[0] == uid:
            лист_финансы.delete_rows(i + 1)
            лог.info("Удалена строка из ФИНАНСОВ: row %d", i + 1)
            break

    # ── ИСТОРИЯ (удаляем последней, чтобы индексы не сместились раньше времени) ──
    лист_история.delete_rows(номер_строки_ист)
    лог.info("Удалена строка из ИСТОРИИ: row %d uid=%s", номер_строки_ист, uid)

    # ── Откат на сайте ──
    изм_откат = инфо_кол if инфо_операция == "Продажа" else -инфо_кол
    рез = апи_обновить_остаток(инфо_товар, изм_откат)
    if not рез.get("success"):
        лог.warning("Не удалось откатить сайт при удалении uid=%s: %s", uid, рез)

    return True, инфо_товар

# ─────────────────────────────────────────────
# Обработчики Telegram
# ─────────────────────────────────────────────

async def cmd_старт(update: Update, context: ContextTypes.DEFAULT_TYPE):
    чат = update.effective_chat.id
    рез = апи_проверить_telegram(чат)
    if рез.get("success"):
        название = рез.get("shopName", SLUG)
        await update.message.reply_text(
            f"👋 С возвращением! Магазин: *{название}*",
            parse_mode="Markdown",
            reply_markup=клавиатура()
        )
        return

    context.user_data.clear()
    context.user_data["шаг"] = "slug"
    await update.message.reply_text("🔐 Введите slug магазина:")


async def cmd_остатки(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await показать_остатки(update)


async def cmd_прибыль(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await показать_прибыль(update)


async def cmd_история(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await показать_историю(update)


async def cmd_помощь(update: Update, context: ContextTypes.DEFAULT_TYPE):
    текст = (
        "ℹ️ *Формат продажи:*\n"
        "`Название цена [кол-во] [поставка N]`\n\n"
        "Примеры:\n"
        "• `Adrenaline Апельсин 450`\n"
        "• `адреналин апельсин 450 2шт поставка 3`\n"
        "• `закуп DLTA мята 300 10шт поставка 1`\n\n"
        "Кнопки меню — остатки, прибыль, история, удаление."
    )
    await update.message.reply_text(текст, parse_mode="Markdown")


async def обработать_сообщение(update: Update, context: ContextTypes.DEFAULT_TYPE):
    чат = update.effective_chat.id
    текст = update.message.text.strip()
    шаг = context.user_data.get("шаг")

    # ── Кнопки меню ──
    if текст == "📦 Остатки":
        await показать_остатки(update)
        return
    if текст == "💰 Прибыль":
        await показать_прибыль(update)
        return
    if текст == "📋 История":
        await показать_историю(update)
        return
    if текст == "🗑 Удалить запись":
        context.user_data["шаг"] = "del_uid"
        await update.message.reply_text(
            "Введите UID операции (из истории, начинается с цифр):"
        )
        return

    # ── Шаги авторизации ──
    if шаг == "del_uid":
        uid = текст
        context.user_data.pop("шаг", None)
        успех, сообщение = удалить_по_uid(uid)
        if успех:
            await update.message.reply_text(f"✅ Запись удалена. Товар: {сообщение}")
        else:
            await update.message.reply_text(f"❌ Ошибка: {сообщение}")
        return

    if шаг == "slug":
        context.user_data["slug_введён"] = текст
        context.user_data["шаг"] = "access_code"
        await update.message.reply_text("🔑 Введите код доступа:")
        return

    if шаг == "access_code":
        context.user_data["ac"] = текст
        context.user_data["шаг"] = "verify_code"
        await update.message.reply_text("🔢 Введите код подтверждения:")
        return

    if шаг == "verify_code":
        slug = context.user_data.get("slug_введён", SLUG)
        ac   = context.user_data.get("ac", "")
        vc   = текст
        рез  = апи_проверить_доступ(slug, ac, vc)
        if рез.get("success"):
            апи_привязать_telegram(slug, чат)
            context.user_data.clear()
            await update.message.reply_text(
                f"✅ Доступ разрешён! Магазин: *{рез.get('shopName', slug)}*",
                parse_mode="Markdown",
                reply_markup=клавиатура()
            )
        else:
            context.user_data.clear()
            await update.message.reply_text(
                f"❌ Ошибка: {рез.get('error', 'неизвестная ошибка')}. "
                "Начните заново: /start"
            )
        return

    # ── Основная логика: продажа / закуп ──
    данные = разобрать_сообщение(текст)

    if not данные["товар"]:
        await update.message.reply_text("❌ Не удалось распознать название товара.")
        return

    сайт = апи_найти_товар(данные["товар"])
    if not сайт.get("found"):
        await update.message.reply_text(
            f"❌ Товар «{данные['товар']}» не найден на сайте.\n"
            "Проверьте название или добавьте синоним в лист ТОВАРЫ."
        )
        return

    # Каноническое имя с сайта
    данные["товар"] = сайт.get("productName", данные["товар"])

    if данные["цена"] is None:
        данные["цена"] = сайт.get("price", 0)

    кол  = данные["количество"]
    опер = данные["операция"]
    изм  = -кол if опер == "Продажа" else кол

    # Обновление сайта
    рез_сайт = апи_обновить_остаток(данные["товар"], изм)

    # Запись в таблицу
    записать_операцию(данные, сайт)

    # Проверяем реальный остаток после обновления
    актуал = апи_найти_товар(данные["товар"])
    остаток = актуал.get("currentStock", рез_сайт.get("newStock", "?"))

    # Формирование ответа
    цена    = данные["цена"]
    себ     = сайт.get("cost", 0)
    оборот  = цена * кол
    приб    = (цена - себ) * кол if себ else None

    эмодзи = "💰" if опер == "Продажа" else "📥"
    ответ = (
        f"{эмодзи} *{опер}*: {данные['товар']}\n"
        f"💵 Цена: {цена} руб × {кол} шт\n"
    )
    if данные["поставка"]:
        ответ += f"📋 Поставка: {данные['поставка']}\n"
    if опер == "Продажа":
        ответ += f"🛒 Оборот: {оборот} руб\n"
        if приб is not None:
            ответ += f"🟢 Чистая прибыль: {приб} руб\n"
    ответ += f"📦 Остаток: {остаток} шт"

    if not рез_сайт.get("success"):
        ответ += f"\n⚠️ Сайт не обновлён: {рез_сайт.get('error', 'неизвестная ошибка')}"

    await update.message.reply_text(ответ, parse_mode="Markdown")

# ─────────────────────────────────────────────
# Просмотровые функции
# ─────────────────────────────────────────────

async def показать_остатки(update: Update):
    try:
        r = requests.get(МАГАЗИН, timeout=10)
        лог.info("shop ← %d", r.status_code)
        if r.status_code != 200:
            await update.message.reply_text("⚠️ Не удалось загрузить остатки (ошибка сайта)")
            return
        д = r.json()
        товары = д.get("products", [])
        кат    = {к["id"]: к["name"] for к in д.get("categories", [])}
        родит  = {к["id"]: к["parentId"] for к in д.get("categories", []) if к.get("parentId")}

        группы: dict = {}
        for т in товары:
            if т.get("hidden"):
                continue
            кат_ид  = т.get("categoryId", "")
            кат_имя = кат.get(кат_ид, "Другое")
            пар_ид  = родит.get(кат_ид)
            если_ест = f" ({кат.get(пар_ид)})" if пар_ид and пар_ид in кат else ""
            заголовок = f"{кат_имя}{если_ест}"

            # Укорачиваем название: убираем общие префиксы
            назв = т["name"]
            for пр in ["D.L.T.A. ", "DLTA ", "CATS WILL ", "CATSWILL ", "Fedors ", "Fedrs "]:
                if назв.startswith(пр):
                    назв = назв[len(пр):]
                    break

            группы.setdefault(заголовок, []).append(
                f"• {назв.strip()} — {т['stock']} шт | {т['price']} руб"
            )

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


async def показать_прибыль(update: Update):
    try:
        строки = лист_финансы.get_all_values()
        итог = 0.0
        for стр in строки[1:]:
            if len(стр) > 5 and стр[5]:  # столбец E (индекс 5 с учётом UID)
                try:
                    итог += float(стр[5])
                except ValueError:
                    pass
        await update.message.reply_text(f"💸 Баланс: {итог:,.0f} руб")
    except Exception as e:
        лог.error("показать_прибыль: %s", e)
        await update.message.reply_text("⚠️ Не удалось получить данные")


async def показать_историю(update: Update):
    try:
        все_строки = лист_история.get_all_values()
        данные = [с for с in все_строки[1:] if с and len(с) >= 6 and с[0]]
        посл = данные[-10:] if len(данные) > 10 else данные

        if not посл:
            await update.message.reply_text("📋 История пуста")
            return

        ответ = "📋 *Последние операции:*\n\n"
        for стр in reversed(посл):
            uid  = стр[0]
            дата = стр[1] if len(стр) > 1 else "?"
            опер = стр[2] if len(стр) > 2 else "?"
            тов  = стр[3] if len(стр) > 3 else "?"
            цена = стр[4] if len(стр) > 4 else "?"
            кол  = стр[5] if len(стр) > 5 else "?"
            ответ += f"`{uid}`\n{дата} — {опер}: {тов}, {цена} руб × {кол} шт\n\n"

        ответ += "🗑 Для удаления: кнопка *«Удалить запись»* → введите UID."
        await update.message.reply_text(ответ, parse_mode="Markdown")
    except Exception as e:
        лог.error("показать_историю: %s", e)
        await update.message.reply_text("⚠️ Не удалось загрузить историю")

# ─────────────────────────────────────────────
# Точка входа
# ─────────────────────────────────────────────

if __name__ == "__main__":
    лог.info("🚀 REESTOR стартует")
    app = ApplicationBuilder().token(ТОКЕН).build()

    app.add_handler(CommandHandler("start",   cmd_старт))
    app.add_handler(CommandHandler("ostatki", cmd_остатки))
    app.add_handler(CommandHandler("balance", cmd_прибыль))
    app.add_handler(CommandHandler("history", cmd_история))
    app.add_handler(CommandHandler("help",    cmd_помощь))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, обработать_сообщение))

    app.run_polling()

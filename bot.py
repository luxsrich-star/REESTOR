import os
import json
import time
import uuid
import logging
from datetime import datetime

import requests
import gspread

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton
)

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

from oauth2client.service_account import (
    ServiceAccountCredentials
)

# ================= LOG =================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

# ================= CONFIG =================

TOKEN = os.environ["TELEGRAM_TOKEN"]

TABLE_ID = os.environ["SPREADSHEET_ID"]

GOOGLE_KEY = json.loads(
    os.environ["GDRIVE_CREDENTIALS"]
)

SLUG = os.environ.get(
    "SHOP_SLUG",
    "shop"
)

SITE = "https://b2bshopb2b.up.railway.app/api/admin"

SHOP_URL = (
    f"https://b2bshopb2b.up.railway.app/api/shop/{SLUG}"
)

# ================= GOOGLE =================

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds = (
    ServiceAccountCredentials
    .from_json_keyfile_dict(
        GOOGLE_KEY,
        scope
    )
)

gs = gspread.authorize(
    creds
)

book = gs.open_by_key(
    TABLE_ID
)

склад = book.worksheet(
    "СКЛАД"
)

фин = book.worksheet(
    "ФИНАНСЫ"
)

ист = book.worksheet(
    "ИСТОРИЯ"
)

тов = book.worksheet(
    "ТОВАРЫ"
)

# ================= MENU =================

def меню():

    return ReplyKeyboardMarkup(

        [
            [
                KeyboardButton(
                    "📦 Остатки"
                ),

                KeyboardButton(
                    "💰 Прибыль"
                )
            ],

            [
                KeyboardButton(
                    "📋 История"
                ),

                KeyboardButton(
                    "🗑 Очистить"
                )
            ]
        ],

        resize_keyboard=True
    )

# ================= HELPERS =================

def uid():

    return str(
        int(
            time.time()*1000
        )
    )


def сейчас():

    return datetime.now().strftime(
        "%d.%m.%Y %H:%M:%S"
    )


def синонимы():

    result = {}

    rows = тов.get_all_values()

    for row in rows[1:]:

        if not row:

            continue

        canon = row[0].strip()

        result[
            canon.lower()
        ] = canon

        if len(row) > 1:

            for s in row[1].split(","):

                s = s.strip()

                if s:

                    result[
                        s.lower()
                    ] = canon

    return result


# ================= API =================

def найти_товар(name):

    try:

        r = requests.get(
            f"{SITE}/find-product",
            params={
                "shopSlug": SLUG,
                "productName": name
            },
            timeout=15
        )

        data = r.json()

        if data.get("found"):
            return data

    except Exception as e:
        logging.error(e)

    # резервный поиск по каталогу

    try:

        r = requests.get(
            SHOP_URL,
            timeout=15
        )

        products = r.json().get(
            "products",
            []
        )

        search = (
            name
            .lower()
            .replace(".", "")
            .strip()
        )

        prefixes = [
            "d l t a ",
            "dlta ",
            "d.l.t.a ",
            "cats will ",
            "catswill ",
            "fedors "
        ]

        for p in products:

            pname = (
                p["name"]
                .lower()
                .replace(".", "")
            )

            short = pname

            for pref in prefixes:

                if short.startswith(pref):

                    short = short[
                        len(pref):
                    ]

            if (
                search in short
                or short in search
                or search in pname
            ):

                return {
                    "found": True,
                    "productId":
                    p["id"],
                    "productName":
                    p["name"],
                    "price":
                    p.get(
                        "price",
                        0
                    ),
                    "currentStock":
                    p.get(
                        "stock",
                        0
                    )
                }

    except Exception as e:

        logging.error(e)

    return {
        "found": False
    }


def обновить_сайт(
        product,
        qty
):

    try:

        r = requests.post(

            f"{SITE}/update-stock",

            json={

                "shopSlug": SLUG,

                "productName": product,

                "quantityChange": qty

            },

            timeout=15

        )

        logging.info(r.text)

        data = r.json()

        return data

    except Exception as e:

        logging.error(e)

        return {
            "success": False
        }


# ================= PARSER =================

data = разбор(text)

logging.info(
    f"INPUT = {text}"
)

logging.info(
    f"PARSED = {data}"
)

site = найти_товар(
    data["товар"]
)

if not site.get(
    "found"
):

    await update.message.reply_text(

        "❌ Товар не найден\n\n"
        "Пример:\n"
        "Adrenaline Апельсин 450 поставка 1"

    )

    return

canonical = site[
    "productName"
]

data[
    "товар"
] = canonical

if data[
    "цена"
] is None:

    data[
        "цена"
    ] = site.get(
        "price",
        0
    )

delta = (

    -data["количество"]

    if data[
        "операция"
    ] == "Продажа"

    else data[
        "количество"
    ]

)

upd = обновить_сайт(
    canonical,
    delta
)

if not upd.get(
    "success"
):

    await update.message.reply_text(
        "⚠️ Сайт не обновился"
    )

    return

запись(
    data,
    site
)

profit = (
    data["цена"]
    * data[
        "количество"
    ]
)

card = (

    "╔══ REESTOR ══╗\n"

    f"📦 {canonical}\n"

    f"💵 {data['цена']} ₽\n"

    f"🔢 x{data['количество']}\n"

    f"📁 Поставка: "
    f"{data['поставка']}\n"

    f"💰 Оборот: "
    f"{profit} ₽\n"

    f"📦 Остаток: "
    f"{upd['newStock']}"

)

await update.message.reply_text(
    card
)


# ================= DELETE =================

def удалить(
        number
):

    rows = (
        ист
        .get_all_values()
    )

    if number < 2:

        return None

    if number > len(rows):

        return None

    row = rows[
        number-1
    ]

    op_id = row[0]

    action = row[2]

    product = row[3]

    qty = int(
        row[5]
    )

    hist = (
        ист
        .get_all_values()
    )

    stock = (
        склад
        .get_all_values()
    )

    money = (
        фин
        .get_all_values()
    )

    for i in range(
        len(stock)-1,
        0,
        -1
    ):

        if stock[i][0] == op_id:

            склад.delete_rows(
                i+1
            )

            break

    for i in range(
        len(money)-1,
        0,
        -1
    ):

        if money[i][0] == op_id:

            фин.delete_rows(
                i+1
            )

            break

    ист.delete_rows(
        number
    )

    delta = (

        qty

        if action
        ==
        "Продажа"

        else -qty
    )

    обновить_сайт(
        product,
        delta
    )

    return product


# ================= COMMANDS =================

async def старт(
        update,
        context
):

    await update.message.reply_text(

        "REESTOR BOT",

        reply_markup=меню()

    )


async def остатки(
        update,
        context
):

    try:

        r = requests.get(
            SHOP_URL,
            timeout=10
        )

        data = r.json()

        products = data.get(
            "products",
            []
        )

        text = "📦 ОСТАТКИ\n\n"

        for p in products:

            if p.get(
                "hidden"
            ):
                continue

            text += (
                f"• "
                f"{p['name']} — "
                f"{p['stock']} шт | "
                f"{p['price']} руб\n"
            )

        await update.message.reply_text(
            text
        )

    except Exception:

        await update.message.reply_text(
            "Ошибка"
        )


async def прибыль(
        update,
        context
):

    rows = (
        фин
        .get_all_values()
    )[1:]

    total = 0

    for r in rows:

        try:

            total += float(
                r[5]
            )

        except:

            pass

    await update.message.reply_text(
        f"💰 {total}"
    )


async def история(
        update,
        context
):

    rows = (
        ист
        .get_all_values()
    )

    if len(rows) <= 1:

        await update.message.reply_text(
            "Пусто"
        )

        return

    text = (
        "📋 История\n\n"
    )

    last = rows[-5:]

    for row in last:

        idx = rows.index(
            row
        ) + 1

        text += (

            f"#{idx} "

            f"{row[3]} "

            f"{row[5]} шт\n"

        )

    await update.message.reply_text(
        text
    )

# ================= MESSAGE =================

async def сообщение(
        update,
        context
):

    text = (
        update
        .message
        .text
        .strip()
    )

    state = (
        context
        .user_data
        .get(
            "state"
        )
    )

    if text == "📦 Остатки":

        await остатки(
            update,
            context
        )

        return

    if text == "💰 Прибыль":

        await прибыль(
            update,
            context
        )

        return

    if text == "📋 История":

        await история(
            update,
            context
        )

        return

    if text == "🗑 Очистить":

        context.user_data[
            "state"
        ] = "delete"

        await update.message.reply_text(
            "Введите номер"
        )

        return

    if state == "delete":

        res = удалить(
            int(text)
        )

        context.user_data.clear()

        await update.message.reply_text(
            f"Удалено {res}"
        )

        return

    data = разбор(
        text
    )

    site = найти_товар(
        data[
            "товар"
        ]
    )

    if not site.get(
        "found"
    ):

        await update.message.reply_text(
            "Товар не найден"
        )

        return

    canonical = site[
        "productName"
    ]

    data[
        "товар"
    ] = canonical

    if data[
        "цена"
    ] is None:

        data[
            "цена"
        ] = site.get(
            "price",
            0
        )

    delta = (

        -data[
            "количество"
        ]

        if data[
            "операция"
        ] == "Продажа"

        else data[
            "количество"
        ]
    )

    upd = обновить_сайт(
        canonical,
        delta
    )

    if not upd.get(
        "success"
    ):

        await update.message.reply_text(
            "Ошибка сайта"
        )

        return

    запись(
        data,
        site
    )

    await update.message.reply_text(

        f"✅ {canonical}\n"

        f"Остаток: "

        f"{upd['newStock']}"

    )

# ================= RUN =================

if __name__ == "__main__":

    app = (
        ApplicationBuilder()
        .token(
            TOKEN
        )
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            старт
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT,
            сообщение
        )
    )

    app.run_polling()
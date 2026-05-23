import os
import json
import time
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

from oauth2client.service_account import ServiceAccountCredentials


logging.basicConfig(level=logging.INFO)

TOKEN = os.environ["TELEGRAM_TOKEN"]
TABLE_ID = os.environ["SPREADSHEET_ID"]
GOOGLE_KEY = json.loads(os.environ["GDRIVE_CREDENTIALS"])

SLUG = os.environ.get("SHOP_SLUG", "shop")

SITE = "https://b2bshopb2b.up.railway.app/api/admin"
SHOP_URL = f"https://b2bshopb2b.up.railway.app/api/shop/{SLUG}"


scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

gs = gspread.authorize(
    ServiceAccountCredentials.from_json_keyfile_dict(
        GOOGLE_KEY,
        scope
    )
)

sh = gs.open_by_key(TABLE_ID)

склад = sh.worksheet("СКЛАД")
фин = sh.worksheet("ФИНАНСЫ")
ист = sh.worksheet("ИСТОРИЯ")
тов = sh.worksheet("ТОВАРЫ")


def uid():
    return str(int(time.time() * 1000))


def меню():
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton("📦 Остатки"),
                KeyboardButton("💰 Прибыль")
            ],
            [
                KeyboardButton("📋 История"),
                KeyboardButton("🗑 Очистить")
            ]
        ],
        resize_keyboard=True
    )


def синонимы():

    r = {}

    rows = тов.get_all_values()[1:]

    for x in rows:

        if not x:
            continue

        canon = x[0].strip()

        r[canon.lower()] = canon

        if len(x) > 1 and x[1]:

            for s in x[1].split(","):

                s = s.strip()

                if s:
                    r[s.lower()] = canon

    return r


def найти_товар(name):

    try:

        r = requests.get(
            f"{SITE}/find-product",
            params={
                "shopSlug": SLUG,
                "productName": name
            },
            timeout=10
        )

        data = r.json()

        if data.get("found"):
            return data

    except Exception as e:
        logging.error(e)

    return {"found": False}


def обновить_сайт(product_name, qty):

    try:

        r = requests.post(
            f"{SITE}/update-stock",
            json={
                "shopSlug": SLUG,
                "productName": product_name,
                "quantityChange": qty
            },
            timeout=15
        )

        logging.info(r.text)

        if r.status_code != 200:
            return {
                "success": False
            }

        return r.json()

    except Exception as e:

        logging.error(e)

        return {
            "success": False
        }


def разбор(text):

    syn = синонимы()

    text = text.strip()

    op = "Продажа"

    if text.lower().startswith("закуп"):

        op = "Закуп"

        text = text[5:].strip()

    supply = None

    if "поставка" in text:

        p = text.split("поставка")

        text = p[0].strip()

        tail = p[1].strip().split()

        if tail and tail[0].isdigit():
            supply = int(tail[0])

    nums = []

    words = []

    for w in text.split():

        c = w.replace(
            "шт",
            ""
        )

        if c.isdigit():
            nums.append(int(c))

        else:
            words.append(w)

    price = nums[0] if nums else None

    qty = nums[1] if len(nums) > 1 else 1

    product = " ".join(words)

    if product.lower() in syn:
        product = syn[product.lower()]

    return {
        "товар": product,
        "цена": price,
        "количество": qty,
        "операция": op,
        "поставка": supply
    }


def запись(data, site):

    id_op = uid()

    date = datetime.now().strftime(
        "%d.%m.%Y %H:%M:%S"
    )

    qty = data["количество"]

    приход = qty if data["операция"] == "Закуп" else 0

    расход = qty if data["операция"] == "Продажа" else 0

    склад.append_row([
        id_op,
        date,
        data["операция"],
        data["поставка"],
        data["товар"],
        приход,
        расход
    ])

    цена = data["цена"]

    оборот = цена * qty

    фин.append_row([
        id_op,
        date,
        data["операция"],
        data["поставка"],
        data["товар"],
        оборот,
        ""
    ])

    ист.append_row([
        id_op,
        date,
        data["операция"],
        data["товар"],
        цена,
        qty,
        data["поставка"]
    ])


def удалить_операцию(row):

    hist = ист.get_all_values()

    if row < 2 or row > len(hist):
        return None

    op = hist[row - 1]

    uid_op = op[0]

    product = op[3]

    qty = int(op[5])

    action = op[2]

    stock_rows = склад.get_all_values()

    for i in range(
        len(stock_rows)-1,
        0,
        -1
    ):

        if stock_rows[i][0] == uid_op:
            склад.delete_rows(i + 1)
            break

    fin_rows = фин.get_all_values()

    for i in range(
        len(fin_rows)-1,
        0,
        -1
    ):

        if fin_rows[i][0] == uid_op:
            фин.delete_rows(i + 1)
            break

    ист.delete_rows(row)

    delta = qty if action == "Продажа" else -qty

    обновить_сайт(
        product,
        delta
    )

    return product


async def сообщение(
        update: Update,
        context:
        ContextTypes.DEFAULT_TYPE
):

    text = update.message.text.strip()

    state = context.user_data.get(
        "state"
    )

    if state == "delete":

        res = удалить_операцию(
            int(text)
        )

        await update.message.reply_text(
            f"Удалено: {res}"
        )

        context.user_data.clear()

        return

    if text == "🗑 Очистить":

        context.user_data[
            "state"
        ] = "delete"

        await update.message.reply_text(
            "Введите номер:"
        )

        return

    data = разбор(text)

    site = найти_товар(
        data["товар"]
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

    data["товар"] = canonical

    if data["цена"] is None:

        data["цена"] = site.get(
            "price",
            0
        )

    delta = (
        -data["количество"]
        if data["операция"]
        == "Продажа"
        else data["количество"]
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
        f"Готово\n"
        f"{canonical}\n"
        f"Осталось: "
        f"{upd['newStock']}"
    )


if __name__ == "__main__":

    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .build()
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT,
            сообщение
        )
    )

    app.run_polling()
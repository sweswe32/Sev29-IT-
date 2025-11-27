import os
from datetime import datetime
from dotenv import load_dotenv
import telebot
from telebot import types
from openpyxl import Workbook, load_workbook

# ================= НАСТРОЙКИ =====================

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TOKEN:
    raise RuntimeError("Не найден TELEGRAM_BOT_TOKEN в .env")

bot = telebot.TeleBot(TOKEN)

EXCEL_FILE = "orders.xlsx"
MAX_ITEMS_PER_ORDER = 10


# ================= СПИСОК ТОВАРОВ =====================

PRODUCTS = [
    {
        "id": 1,
        "name": "Фигурка дракона",
        "price": 500,
        "model": "dragon.stl",
        "description": "Дракон 10 см, PLA пластик.",
        "image": "images/dragon.jpg",
    },
    {
        "id": 2,
        "name": "Держатель телефона",
        "price": 300,
        "model": "phone_holder.stl",
        "description": "Универсальный держатель для смартфона.",
        "image": "images/phone_holder.jpg",
    },
    {
        "id": 3,
        "name": "Ключница настенная",
        "price": 450,
        "model": "key_holder.stl",
        "description": "Ключница на 5 крючков.",
        "image": "images/key_holder.jpg",
    },
]


# ================= ХРАНЕНИЕ СОСТОЯНИЙ =====================

user_carts = {}      # user_id -> список товаров
user_states = {}     # user_id -> state
pending_product = {} # user_id -> product_id
checkout_data = {}   # user_id -> { fio, phone }
orders_queue = []    # очередь заказов


# ================ EXCEL ==========================

def init_workbook():
    if os.path.exists(EXCEL_FILE):
        return

    wb = Workbook()
    ws = wb.active
    ws.title = "Заказы"

    headers = ["Дата заказа", "ФИО", "Телефон"]

    for i in range(1, MAX_ITEMS_PER_ORDER + 1):
        headers.extend([
            f"Имя товара {i}",
            f"Кол-во {i}",
            f"Цена за шт. {i}",
            f"Сумма {i}",
            f"Модель {i}"
        ])

    ws.append(headers)
    wb.save(EXCEL_FILE)


def save_order_to_excel(fio: str, phone: str, items: list):
    init_workbook()
    wb = load_workbook(EXCEL_FILE)
    ws = wb.active

    date_str = datetime.now().strftime("%d.%m.%Y %H:%M")
    row = [date_str, fio, phone]

    for i in range(MAX_ITEMS_PER_ORDER):
        if i < len(items):
            item = items[i]
            qty = item["qty"]
            price = item["price"]
            total = qty * price

            row.extend([
                item["name"],
                qty,
                price,
                total,
                item["model"],
            ])
        else:
            row.extend(["", "", "", "", ""])

    ws.append(row)
    wb.save(EXCEL_FILE)


# ================= ВСПОМОГАТЕЛЬНОЕ =====================

def get_product_by_id(pid):
    for p in PRODUCTS:
        if p["id"] == pid:
            return p
    return None


def get_cart(user_id):
    return user_carts.get(user_id, [])


def add_to_cart(user_id, product, qty):
    cart = user_carts.setdefault(user_id, [])
    cart.append({
        "name": product["name"],
        "qty": qty,
        "price": product["price"],
        "model": product["model"],
    })


def format_cart_text(user_id):
    cart = get_cart(user_id)
    if not cart:
        return "Корзина пуста."

    total = 0
    lines = []
    for i, item in enumerate(cart, 1):
        s = item["qty"] * item["price"]
        total += s
        lines.append(f"{i}. {item['name']} — {item['qty']} шт × {item['price']} ₽ = {s} ₽")

    lines.append(f"\nИТОГО: {total} ₽")
    return "\n".join(lines)


def main_menu_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Каталог товаров", "Корзина")
    return kb


def cart_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Оформить заказ", "Очистить корзину")
    kb.add("Каталог товаров")
    return kb


def send_catalog(chat_id):
    for p in PRODUCTS:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(
            text="Добавить в корзину",
            callback_data=f"add_{p['id']}"
        ))

        caption = (
            f"<b>{p['name']}</b>\n"
            f"Цена: {p['price']} ₽\n"
            f"{p['description']}\n"
            f"Модель: <code>{p['model']}</code>"
        )

        if os.path.exists(p["image"]):
            with open(p["image"], "rb") as img:
                bot.send_photo(chat_id, img, caption=caption, parse_mode="HTML", reply_markup=kb)
        else:
            bot.send_message(chat_id, caption, parse_mode="HTML", reply_markup=kb)


# ================== ХЕНДЛЕРЫ ==========================

@bot.message_handler(commands=["start"])
def start(message):
    user_carts[message.from_user.id] = []
    user_states[message.from_user.id] = None
    bot.send_message(message.chat.id,
                     "Добро пожаловать! Это бот для заказов 3D-печати.",
                     reply_markup=main_menu_keyboard())


@bot.message_handler(func=lambda m: m.text == "Каталог товаров")
def catalog(message):
    send_catalog(message.chat.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("add_"))
def add_handler(call):
    user_id = call.from_user.id
    product_id = int(call.data.split("_")[1])

    pending_product[user_id] = product_id
    user_states[user_id] = "waiting_qty"

    bot.send_message(call.message.chat.id,
                     "Введите количество товара:")
    bot.answer_callback_query(call.id)


@bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == "waiting_qty")
def qty_handler(message):
    user_id = message.from_user.id

    if not message.text.isdigit() or int(message.text) <= 0:
        bot.send_message(message.chat.id, "Введите корректное число.")
        return

    qty = int(message.text)
    product = get_product_by_id(pending_product[user_id])

    add_to_cart(user_id, product, qty)

    user_states[user_id] = None
    pending_product.pop(user_id)

    bot.send_message(message.chat.id,
                     f"Добавлено в корзину: {product['name']} — {qty} шт.",
                     reply_markup=cart_keyboard())


@bot.message_handler(func=lambda m: m.text == "Корзина")
def show_cart(message):
    bot.send_message(message.chat.id,
                     format_cart_text(message.from_user.id),
                     reply_markup=cart_keyboard())


@bot.message_handler(func=lambda m: m.text == "Очистить корзину")
def clear_cart(message):
    user_carts[message.from_user.id] = []
    bot.send_message(message.chat.id,
                     "Корзина очищена.",
                     reply_markup=main_menu_keyboard())


@bot.message_handler(func=lambda m: m.text == "Оформить заказ")
def checkout_start(message):
    if not get_cart(message.from_user.id):
        bot.send_message(message.chat.id, "Корзина пуста.")
        return

    user_states[message.from_user.id] = "waiting_fio"
    bot.send_message(message.chat.id, "Введите ваше ФИО:")


@bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == "waiting_fio")
def fio(message):
    fio = message.text.strip()
    if len(fio.split()) < 2:
        bot.send_message(message.chat.id, "Введите ФИО полностью.")
        return

    uid = message.from_user.id
    checkout_data[uid] = {"fio": fio}
    user_states[uid] = "waiting_phone"

    bot.send_message(message.chat.id, "Введите номер телефона:")


@bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == "waiting_phone")
def phone(message):
    phone = message.text.strip()
    uid = message.from_user.id

    checkout_data[uid]["phone"] = phone
    fio = checkout_data[uid]["fio"]
    cart = get_cart(uid)

    # Excel
    save_order_to_excel(fio, phone, cart)

    # очередь
    orders_queue.append({
        "timestamp": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "fio": fio,
        "phone": phone,
        "items": cart.copy()
    })

    # очистка
    user_carts[uid] = []
    user_states[uid] = None
    checkout_data.pop(uid)

    bot.send_message(message.chat.id,
                     "Заказ оформлен! Он добавлен в очередь.",
                     reply_markup=main_menu_keyboard())


# ================ ОЧЕРЕДЬ ==================

@bot.message_handler(commands=["queue"])
def queue_view(message):
    if not orders_queue:
        bot.send_message(message.chat.id, "Очередь пуста.")
        return

    text = "📦 Очередь заказов:\n\n"
    for i, o in enumerate(orders_queue, 1):
        text += f"{i}. {o['fio']} — {o['phone']} — {o['timestamp']}\n"

    text += "\nИспользуйте /done N для завершения"
    bot.send_message(message.chat.id, text)


@bot.message_handler(commands=["done"])
def done(message):
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        bot.send_message(message.chat.id, "Формат: /done 1")
        return

    idx = int(parts[1]) - 1

    if idx < 0 or idx >= len(orders_queue):
        bot.send_message(message.chat.id, "Неверный номер заказа.")
        return

    order = orders_queue.pop(idx)
    bot.send_message(message.chat.id,
                     f"Заказ {order['fio']} завершён.")


@bot.message_handler(commands=["clearqueue"])
def clear_q(message):
    orders_queue.clear()
    bot.send_message(message.chat.id, "Очередь очищена.")


# фолбек
@bot.message_handler(func=lambda m: True)
def fallback(message):
    bot.send_message(message.chat.id,
                     "Используйте кнопки или команды.",
                     reply_markup=main_menu_keyboard())


# запуск
print("Бот запущен...")
bot.infinity_polling()

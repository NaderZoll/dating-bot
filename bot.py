import asyncio
import os
from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandStart
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from pymongo import MongoClient
from dotenv import load_dotenv
import requests

# Загружаем переменные окружения
load_dotenv()

# Инициализация бота и диспетчера
print("Initializing bot...")
try:
    bot = Bot(token=os.getenv("BOT_TOKEN"))
    dp = Dispatcher()
    print("Bot initialized successfully.")
except Exception as e:
    print(f"Failed to initialize bot: {e}")
    raise

# Подключение к MongoDB
print("Connecting to MongoDB...")
try:
    mongo_client = MongoClient(os.getenv("MONGODB_URI"))
    db = mongo_client["dating_bot"]
    users_collection = db["users"]
    mongo_client.server_info()
    print("Connected to MongoDB successfully.")
except Exception as e:
    print(f"Failed to connect to MongoDB: {e}")
    raise

# Клавиатуры
def get_privacy_keyboard():
    return ReplyKeyboardMarkup(resize_keyboard=True).add(
        KeyboardButton("Я согласен с политикой конфиденциальности")
    )

def get_main_menu():
    return ReplyKeyboardMarkup(resize_keyboard=True).add(
        KeyboardButton("Заполнить анкету"),
        KeyboardButton("Найти пару")
    )

# Обработчики команд
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    user = users_collection.find_one({"user_id": user_id})

    if user and user.get("privacy_accepted", False):
        await message.answer("Добро пожаловать обратно!", reply_markup=get_main_menu())
    else:
        await message.answer("Привет! Подтверди согласие с политикой конфиденциальности.", reply_markup=get_privacy_keyboard())

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "Я бот для знакомств! Вот что я умею:\n"
        "/start - Начать работу\n"
        "/help - Показать справку\n"
        "Заполнить анкету - О себе\n"
        "Найти пару - Поиск совпадений"
    )

# Обработчик согласия с политикой конфиденциальности
@dp.message(lambda message: message.text == "Я согласен с политикой конфиденциальности")
async def privacy_accepted(message: types.Message):
    user_id = message.from_user.id
    users_collection.update_one({"user_id": user_id}, {"$set": {"privacy_accepted": True}}, upsert=True)
    await message.answer("Спасибо! Теперь можно начать.", reply_markup=get_main_menu())

# Заполнение анкеты
@dp.message(lambda message: message.text == "Заполнить анкету")
async def fill_profile(message: types.Message):
    user_id = message.from_user.id
    user = users_collection.find_one({"user_id": user_id})

    if not user or not user.get("privacy_accepted", False):
        await message.answer("Сначала согласись с политикой конфиденциальности.")
        return

    await message.answer("Введите ваше имя:")
    dp.register_message_handler(save_name, lambda m: m.from_user.id == user_id)

async def save_name(message: types.Message):
    user_id = message.from_user.id
    users_collection.update_one({"user_id": user_id}, {"$set": {"name": message.text}}, upsert=True)
    await message.answer("Имя сохранено! Введите ваш возраст:")
    dp.register_message_handler(save_age, lambda m: m.from_user.id == user_id)

async def save_age(message: types.Message):
    user_id = message.from_user.id
    try:
        age = int(message.text)
        users_collection.update_one({"user_id": user_id}, {"$set": {"age": age}}, upsert=True)
        await message.answer("Возраст сохранён! Укажите ваши интересы:")
        dp.register_message_handler(save_interests, lambda m: m.from_user.id == user_id)
    except ValueError:
        await message.answer("Введите возраст числом.")

async def save_interests(message: types.Message):
    user_id = message.from_user.id
    interests = [i.strip() for i in message.text.split(",")]
    users_collection.update_one({"user_id": user_id}, {"$set": {"interests": interests}}, upsert=True)
    await message.answer("Анкета заполнена!", reply_markup=get_main_menu())

# Поиск пары
@dp.message(lambda message: message.text == "Найти пару")
async def find_match(message: types.Message):
    user_id = message.from_user.id
    user = users_collection.find_one({"user_id": user_id})

    if not user or not user.get("interests"):
        await message.answer("Заполни анкету сначала.")
        return

    user_interests = set(user["interests"])
    matches = list(users_collection.find({"user_id": {"$ne": user_id}, "interests": {"$in": list(user_interests)}}))

    if not matches:
        await message.answer("Нет совпадений. Попробуй позже!")
    else:
        for match in matches:
            await message.answer(f"Найдена пара: {match.get('name', 'Без имени')} ({match.get('age', 'не указан')})")

# Обработчик вебхука
async def webhook_handler(request):
    print("Received webhook request")
    try:
        update = await request.json()
        await dp.feed_raw_update(bot, update)
        return web.Response()
    except Exception as e:
        print(f"Error processing webhook: {e}")
        return web.Response(status=500)

# Запуск бота
async def start_bot():
    try:
        await bot.set_webhook("https://dating-bot-p9ks.onrender.com/webhook")
        print("Webhook set successfully.")
    except Exception as e:
        print(f"Webhook setup failed: {e}")

app = web.Application()
app.add_routes([
    web.post("/webhook", webhook_handler),
])

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_bot())
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))

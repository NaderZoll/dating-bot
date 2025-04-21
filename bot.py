import asyncio
import os
from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandStart
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from pymongo import MongoClient
from dotenv import load_dotenv
import requests

# Загружаем переменные окружения из .env файла
load_dotenv()

# Инициализация бота и диспетчера
bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher()

# Подключение к MongoDB
mongo_client = MongoClient(os.getenv("MONGODB_URI"))
db = mongo_client["dating_bot"]
users_collection = db["users"]

# Клавиатура для согласия с политикой конфиденциальности
def get_privacy_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton("Я согласен с политикой конфиденциальности"))
    return keyboard

# Клавиатура для главного меню
def get_main_menu():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton("Заполнить анкету"))
    keyboard.add(KeyboardButton("Найти пару"))
    return keyboard

# Обработчик команды /start
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    user = users_collection.find_one({"user_id": user_id})

    if user and user.get("privacy_accepted", False):
        await message.answer("Добро пожаловать обратно! Выберите действие:", reply_markup=get_main_menu())
    else:
        await message.answer(
            "Привет! Прежде чем начать, пожалуйста, подтвердите согласие с нашей политикой конфиденциальности.",
            reply_markup=get_privacy_keyboard()
        )

# Обработчик команды /help
@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "Я бот для знакомств! Вот что я умею:\n"
        "/start - Начать работу\n"
        "/help - Показать эту справку\n"
        "Заполнить анкету - Расскажите о себе\n"
        "Найти пару - Найти подходящего человека"
    )

# Обработчик согласия с политикой конфиденциальности
@dp.message(lambda message: message.text == "Я согласен с политикой конфиденциальности")
async def privacy_accepted(message: types.Message):
    user_id = message.from_user.id
    users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id, "privacy_accepted": True}},
        upsert=True
    )
    await message.answer("Спасибо за согласие! Теперь вы можете начать.", reply_markup=get_main_menu())

# Обработчик заполнения анкеты
@dp.message(lambda message: message.text == "Заполнить анкету")
async def fill_profile(message: types.Message):
    user_id = message.from_user.id
    user = users_collection.find_one({"user_id": user_id})

    if not user or not user.get("privacy_accepted", False):
        await message.answer("Пожалуйста, сначала согласитесь с политикой конфиденциальности.")
        return

    # Здесь можно добавить пошаговое заполнение анкеты (имя, возраст, интересы и т.д.)
    # Для примера просто сохраним базовую информацию
    await message.answer("Введите ваше имя:")
    dp.register_message_handler(save_name, user_id=user_id)

async def save_name(message: types.Message):
    user_id = message.from_user.id
    name = message.text
    users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"name": name}},
        upsert=True
    )
    await message.answer("Имя сохранено! Введите ваш возраст:")
    dp.register_message_handler(save_age, user_id=user_id)

async def save_age(message: types.Message):
    user_id = message.from_user.id
    try:
        age = int(message.text)
        users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"age": age}},
            upsert=True
        )
        await message.answer("Возраст сохранён! Укажите ваши интересы (через запятую, например: кино, музыка):")
        dp.register_message_handler(save_interests, user_id=user_id)
    except ValueError:
        await message.answer("Пожалуйста, введите возраст в виде числа.")
        return

async def save_interests(message: types.Message):
    user_id = message.from_user.id
    interests = [interest.strip() for interest in message.text.split(",")]
    users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"interests": interests}},
        upsert=True
    )
    await message.answer("Анкета заполнена! Теперь вы можете искать пару.", reply_markup=get_main_menu())
    dp.message.handlers.clear()  # Очищаем временные обработчики

# Обработчик поиска пары
@dp.message(lambda message: message.text == "Найти пару")
async def find_match(message: types.Message):
    user_id = message.from_user.id
    user = users_collection.find_one({"user_id": user_id})

    if not user or not user.get("interests"):
        await message.answer("Пожалуйста, сначала заполните анкету.")
        return

    user_interests = set(user.get("interests", []))
    # Ищем пользователей с совпадающими интересами
    matches = users_collection.find({
        "user_id": {"$ne": user_id},
        "interests": {"$in": list(user_interests)}
    })

    if matches.count() == 0:
        await message.answer("К сожалению, подходящих пар не найдено. Попробуйте позже!")
        return

    for match in matches:
        await message.answer(f"Найдена пара: {match.get('name', 'Без имени')} ({match.get('age', 'возраст не указан')})")
    await message.answer("Поиск завершён! Выберите действие:", reply_markup=get_main_menu())

# Авторизация через ВКонтакте
async def vk_callback(request):
    code = request.query.get("code")
    if not code:
        return web.Response(text="VK Authorization failed: No code provided")

    # Обмен кода на токен
    try:
        response = requests.get(
            "https://oauth.vk.com/access_token",
            params={
                "client_id": os.getenv("VK_CLIENT_ID"),
                "client_secret": os.getenv("VK_CLIENT_SECRET"),
                "redirect_uri": os.getenv("VK_REDIRECT_URI"),
                "code": code
            }
        )
        data = response.json()
        if "access_token" in data:
            # Сохраняем токен в базе данных
            user_id = request.query.get("state")  # Используем state для передачи user_id
            users_collection.update_one(
                {"user_id": int(user_id)},
                {"$set": {"vk_token": data["access_token"]}},
                upsert=True
            )
            return web.Response(text="VK Authorization successful!")
        else:
            return web.Response(text=f"VK Authorization failed: {data.get('error_description', 'Unknown error')}")
    except Exception as e:
        return web.Response(text=f"VK Authorization failed: {str(e)}")

# Авторизация через Twitch
async def twitch_callback(request):
    code = request.query.get("code")
    if not code:
        return web.Response(text="Twitch Authorization failed: No code provided")

    # Обмен кода на токен
    try:
        response = requests.post(
            "https://id.twitch.tv/oauth2/token",
            params={
                "client_id": os.getenv("TWITCH_CLIENT_ID"),
                "client_secret": os.getenv("TWITCH_CLIENT_SECRET"),
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": os.getenv("TWITCH_REDIRECT_URI")
            }
        )
        data = response.json()
        if "access_token" in data:
            user_id = request.query.get("state")
            users_collection.update_one(
                {"user_id": int(user_id)},
                {"$set": {"twitch_token": data["access_token"]}},
                upsert=True
            )

            # Получаем интересы пользователя через Twitch API
            headers = {
                "Authorization": f"Bearer {data['access_token']}",
                "Client-ID": os.getenv("TWITCH_CLIENT_ID")
            }
            user_response = requests.get("https://api.twitch.tv/helix/users", headers=headers)
            twitch_user = user_response.json().get("data", [{}])[0]
            twitch_user_id = twitch_user.get("id")

            # Получаем подписки пользователя (интересы)
            subscriptions_response = requests.get(
                f"https://api.twitch.tv/helix/channels/followed?user_id={twitch_user_id}",
                headers=headers
            )
            subscriptions = subscriptions_response.json().get("data", [])
            interests = [sub["broadcaster_name"] for sub in subscriptions]

            users_collection.update_one(
                {"user_id": int(user_id)},
                {"$set": {"interests": interests}},
                upsert=True
            )
            return web.Response(text="Twitch Authorization successful! Interests updated.")
        else:
            return web.Response(text=f"Twitch Authorization failed: {data.get('error_description', 'Unknown error')}")
    except Exception as e:
        return web.Response(text=f"Twitch Authorization failed: {str(e)}")

# Тестовый маршрут для проверки доступности Render
async def test_route(request):
    return web.Response(text="Render is working!")

# Обработчик вебхука
async def webhook_handler(request):
    try:
        update = await request.json()
        await dp.feed_raw_update(bot, update)
        return web.Response()
    except Exception as e:
        print(f"Error processing webhook: {e}")
        return web.Response(status=500)

# Обновлённый запуск бота
if __name__ == "__main__":
    app = web.Application()
    app.add_routes([
        web.get("/vk_callback", vk_callback),
        web.get("/twitch_callback", twitch_callback),
        web.get("/test", test_route),
        web.post("/webhook", webhook_handler),  # Добавляем маршрут для вебхука вручную
    ])

    # Устанавливаем вебхук вручную перед запуском
    async def start_bot():
        try:
            webhook_url = "https://dating-bot-p9ks.onrender.com/webhook"
            print(f"Setting webhook to: {webhook_url}")
            await bot.set_webhook(webhook_url)
            print(f"Webhook successfully set to {webhook_url}")
        except Exception as e:
            print(f"Failed to set webhook: {e}")
            raise

    async def stop_bot():
        try:
            print("Removing webhook...")
            await bot.delete_webhook()
            print("Webhook successfully deleted")
        except Exception as e:
            print(f"Failed to delete webhook: {e}")

    # Запускаем приложение
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(start_bot())  # Устанавливаем вебхук
        web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
    finally:
        loop.run_until_complete(stop_bot())  # Удаляем вебхук при завершении
        loop.close()
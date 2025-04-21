import asyncio
import os
from datetime import datetime
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import pymongo
import requests
from urllib.parse import urlencode
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

# Загрузка переменных окружения
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
VK_CLIENT_ID = os.getenv("VK_CLIENT_ID")
VK_CLIENT_SECRET = os.getenv("VK_CLIENT_SECRET")
VK_REDIRECT_URI = os.getenv("VK_REDIRECT_URI")


# Инициализация бота
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Подключение к MongoDB
# Если используете локальный MongoDB, оставьте как есть
# Если используете MongoDB Atlas, замените на вашу строку подключения, например:
# client = pymongo.MongoClient("mongodb+srv://admin:yourpassword@cluster0.mongodb.net/")
client = pymongo.MongoClient(os.getenv("MONGODB_URI"))
db = client["dating_bot"]
users_collection = db["users"]

# Состояния для FSM
class ProfileStates(StatesGroup):
    waiting_for_location = State()
    waiting_for_city = State()
    waiting_for_age = State()
    waiting_for_gender = State()
    waiting_for_interests = State()
    waiting_for_photo = State()

# Команда /start
@dp.message(Command("start"))
async def start_command(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or "No username"

    user = users_collection.find_one({"user_id": user_id})
    if not user:
        users_collection.insert_one({
            "user_id": user_id,
            "username": username,
            "auth": {"telegram": True, "vk": False, "twitch": False},
            "profile": {},
            "location": {},
            "likes": [],
            "liked_by": [],
            "chats": {},
            "reports": [],
            "agreed_to_privacy": False
        })

    if user and user.get("agreed_to_privacy", False):
        vk_auth_url = f"https://oauth.vk.com/authorize?{urlencode({'client_id': VK_CLIENT_ID, 'redirect_uri': VK_REDIRECT_URI, 'response_type': 'code', 'state': str(user_id)})}"
        twitch_auth_url = f"https://id.twitch.tv/oauth2/authorize?{urlencode({'client_id': TWITCH_CLIENT_ID, 'redirect_uri': TWITCH_REDIRECT_URI, 'response_type': 'code', 'scope': 'user:read:subscriptions', 'state': str(user_id)})}"

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Войти через ВКонтакте", url=vk_auth_url)],
            [InlineKeyboardButton(text="Войти через Twitch", url=twitch_auth_url)],
            [InlineKeyboardButton(text="Указать местоположение", callback_data="set_location")]
        ])
        await message.reply(
            f"Привет, {username}! Это бот для знакомств. Авторизуйся и укажи местоположение:",
            reply_markup=keyboard
        )
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Согласен", callback_data="agree_privacy")]
        ])
        await message.reply(
            "Пожалуйста, согласись с политикой конфиденциальности перед использованием бота.\n"
            "Ознакомиться: /privacy",
            reply_markup=keyboard
        )

# Обработка местоположения
@dp.callback_query(lambda c: c.data == "set_location")
async def set_location(callback: types.CallbackQuery, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Поделиться геолокацией", callback_data="share_geo")],
        [InlineKeyboardButton(text="Указать город вручную", callback_data="manual_city")]
    ])
    await callback.message.reply("Как указать местоположение?", reply_markup=keyboard)
    await state.set_state(ProfileStates.waiting_for_location)

@dp.callback_query(lambda c: c.data == "share_geo", ProfileStates.waiting_for_location)
async def request_geo(callback: types.CallbackQuery, state: FSMContext):
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Поделиться геолокацией", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await callback.message.reply("Нажми кнопку ниже:", reply_markup=keyboard)
    await state.set_state(ProfileStates.waiting_for_location)

@dp.message(lambda message: message.location, ProfileStates.waiting_for_location)
async def process_location(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    location = {
        "latitude": message.location.latitude,
        "longitude": message.location.longitude
    }
    users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"location": location}}
    )
    await message.reply("Местоположение сохранено! Заполни анкету: /profile")
    await state.clear()

@dp.callback_query(lambda c: c.data == "manual_city", ProfileStates.waiting_for_location)
async def manual_city(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.reply("Введи название города:")
    await state.set_state(ProfileStates.waiting_for_city)

@dp.message(ProfileStates.waiting_for_city)
async def process_city(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    city = message.text.strip()
    users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"location": {"city": city}}}
    )
    await message.reply("Город сохранён! Заполни анкету: /profile")
    await state.clear()

# Команда /profile
@dp.message(Command("profile"))
async def profile_command(message: types.Message, state: FSMContext):
    await message.reply("Укажи свой возраст (число):")
    await state.set_state(ProfileStates.waiting_for_age)

@dp.message(ProfileStates.waiting_for_age)
async def process_age(message: types.Message, state: FSMContext):
    try:
        age = int(message.text)
        if 18 <= age <= 100:
            await state.update_data(age=age)
            keyboard = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="Мужской"), KeyboardButton(text="Женский")]
                ],
                resize_keyboard=True,
                one_time_keyboard=True
            )
            await message.reply("Укажи свой пол:", reply_markup=keyboard)
            await state.set_state(ProfileStates.waiting_for_gender)
        else:
            await message.reply("Возраст должен быть от 18 до 100. Попробуй снова:")
    except ValueError:
        await message.reply("Введи число. Попробуй снова:")

@dp.message(ProfileStates.waiting_for_gender)
async def process_gender(message: types.Message, state: FSMContext):
    gender = message.text.lower()
    if gender in ["мужской", "женский"]:
        await state.update_data(gender=gender)
        await message.reply("Укажи свои интересы (например, игры, музыка, спорт):")
        await state.set_state(ProfileStates.waiting_for_interests)
    else:
        await message.reply("Выбери 'Мужской' или 'Женский'.")

@dp.message(ProfileStates.waiting_for_interests)
async def process_interests(message: types.Message, state: FSMContext):
    interests = message.text.strip().split(",")
    await state.update_data(interests=[i.strip() for i in interests])
    await message.reply("Отправь своё фото:")
    await state.set_state(ProfileStates.waiting_for_photo)

@dp.message(lambda message: message.photo, ProfileStates.waiting_for_photo)
async def process_photo(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_data = await state.get_data()
    photo_id = message.photo[-1].file_id
    users_collection.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "profile": {
                    "age": user_data["age"],
                    "gender": user_data["gender"],
                    "interests": user_data["interests"],
                    "photo_id": photo_id
                }
            }
        }
    )
    await message.reply("Анкета сохранена! Начни поиск: /find")
    await state.clear()

# Команда /find
@dp.message(Command("find"))
async def find_command(message: types.Message):
    user_id = message.from_user.id
    user = users_collection.find_one({"user_id": user_id})
    if not user.get("profile", {}).get("photo_id"):
        await message.reply("Сначала заполни анкету: /profile")
        return

    # Простой поиск: ищем пользователей из того же города
    user_location = user.get("location", {})
    city = user_location.get("city") if "city" in user_location else None
    query = {
        "user_id": {"$ne": user_id},
        "profile.photo_id": {"$exists": True}
    }
    if city:
        query["location.city"] = city

    other_user = users_collection.find_one(query)
    if not other_user:
        await message.reply("Пока нет подходящих анкет. Приглашай друзей!")
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Лайк", callback_data=f"like_{other_user['user_id']}")],
        [InlineKeyboardButton(text="Пропустить", callback_data="skip")]
    ])
    location = other_user.get("location", {})
    location_str = location.get("city", "Не указано") if "city" in location else "Геолокация"
    await bot.send_photo(
        chat_id=message.chat.id,
        photo=other_user["profile"]["photo_id"],
        caption=f"{other_user['username']}, {other_user['profile']['age']}, {other_user['profile']['gender']}\n"
                f"Интересы: {', '.join(other_user['profile']['interests'])}\n"
                f"Местоположение: {location_str}",
        reply_markup=keyboard
    )

@dp.callback_query(lambda c: c.data.startswith("like_"))
async def process_like(callback: types.CallbackQuery):
    liker_id = callback.from_user.id
    liked_id = int(callback.data.split("_")[1])

    # Добавляем лайк
    users_collection.update_one(
        {"user_id": liked_id},
        {"$addToSet": {"liked_by": liker_id}}
    )
    users_collection.update_one(
        {"user_id": liker_id},
        {"$addToSet": {"likes": liked_id}}
    )

    # Проверяем взаимный лайк
    liked_user = users_collection.find_one({"user_id": liked_id})
    if liker_id in liked_user.get("likes", []):
        await bot.send_message(
            liker_id,
            f"У вас взаимный лайк с @{liked_user['username']}! Напиши: /chat {liked_id}"
        )
        await bot.send_message(
            liked_id,
            f"У вас взаимный лайк с @{callback.from_user.username}! Напиши: /chat {liked_id}"
        )
    else:
        await callback.message.reply("Лайк отправлен! Продолжай: /find")

@dp.callback_query(lambda c: c.data == "skip")
async def process_skip(callback: types.CallbackQuery):
    await callback.message.reply("Пропущено. Продолжай: /find")

# Команда /chat (заглушка)
@dp.message(Command("chat"))
async def chat_command(message: types.Message):
    args = message.text.split()
    if len(args) != 2:
        await message.reply("Используй: /chat user_id")
        return
    await message.reply("Чат с пользователем (функция в разработке).")

# Настройка вебхуков
async def on_startup(_):
    await bot.set_webhook(f"https://dating-bot.onrender.com/webhook")

async def on_shutdown(_):
    await bot.delete_webhook()

# Обновлённый запуск бота
if __name__ == "__main__":
    app = web.Application()
    webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_requests_handler.register(app, path="/webhook")
    setup_application(app, dp, bot=bot)
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))

    # Обработка OAuth для ВКонтакте
async def vk_callback(request):
    code = request.query.get("code")
    state = request.query.get("state")  # Telegram user_id
    if not code or not state:
        return web.Response(text="Ошибка авторизации VK")

    # Обмен code на access_token
    response = requests.get(
        f"https://oauth.vk.com/access_token?client_id={VK_CLIENT_ID}&client_secret={VK_CLIENT_SECRET}&redirect_uri={VK_REDIRECT_URI}&code={code}"
    )
    data = response.json()
    if "access_token" not in data:
        return web.Response(text="Ошибка получения токена VK")

    # Получение данных пользователя
    user_response = requests.get(
        f"https://api.vk.com/method/users.get?access_token={data['access_token']}&v=5.131"
    )
    user_data = user_response.json()
    if "response" not in user_data or not user_data["response"]:
        return web.Response(text="Ошибка получения данных VK")

    # Сохранение данных
    vk_user = user_data["response"][0]
    user_id = int(state)
    users_collection.update_one(
        {"user_id": user_id},
        {"$set": {
            "auth.vk": True,
            "vk_data": {
                "id": vk_user["id"],
                "first_name": vk_user["first_name"],
                "last_name": vk_user["last_name"]
            }
        }}
    )
    await bot.send_message(user_id, f"Авторизация через ВКонтакте успешна! Имя: {vk_user['first_name']}")
    return web.Response(text=f"Авторизация VK успешна! Имя: {vk_user['first_name']}")


# Настройка вебхуков
async def on_startup(*args, **kwargs):
    try:
        print("Starting webhook setup...")
        webhook_url = "https://dating-bot.onrender.com/webhook"
        print(f"Setting webhook to: {webhook_url}")
        await bot.set_webhook(webhook_url)
        print(f"Webhook successfully set to {webhook_url}")
    except Exception as e:
        print(f"Failed to set webhook: {e}")
        raise  # Перебрасываем исключение, чтобы увидеть его в логах Render

async def on_shutdown(*args, **kwargs):
    try:
        print("Removing c webhook...")
        await bot.delete_webhook()
        print("Webhook successfully deleted")
    except Exception as e:
        print(f"Failed to delete webhook: {e}")

# Обновлённый запуск бота
if __name__ == "__main__":
    app = web.Application()
    app.add_routes([
        web.get("/vk_callback", vk_callback),
        web.get("/twitch_callback", twitch_callback)
    ])
    webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_requests_handler.register(app, path="/webhook")
    setup_application(app, dp, bot=bot)

    # Устанавливаем вебхук вручную перед запуском
    async def start_bot():
        try:
            webhook_url = "https://dating-bot.onrender.com/webhook"
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
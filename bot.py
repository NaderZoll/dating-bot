import asyncio
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import pymongo

# Загрузка переменных окружения
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Подключение к MongoDB
# Если используете локальный MongoDB, оставьте как есть
# Если используете MongoDB Atlas, замените на вашу строку подключения, например:
# client = pymongo.MongoClient("mongodb+srv://admin:yourpassword@cluster0.mongodb.net/")
client = pymongo.MongoClient("mongodb+srv://devilfrost1:QxIV10hynXCEl48M@datebot.ln0utwa.mongodb.net/?retryWrites=true&w=majority&appName=DateBot")
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
async def start_command(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or "No username"

    # Проверка, есть ли пользователь в базе
    user = users_collection.find_one({"user_id": user_id})
    if not user:
        users_collection.insert_one({
            "user_id": user_id,
            "username": username,
            "profile": {},
            "location": {},
            "likes": [],
            "liked_by": []
        })

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Указать местоположение", callback_data="set_location")]
    ])
    await message.reply(
        f"Привет, {username}! Это бот для знакомств. Укажи местоположение и заполни анкету:",
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

# Запуск бота
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
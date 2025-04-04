from datetime import datetime, timedelta
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
import aiohttp  # Используем aiohttp для асинхронных запросов
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message, ParseMode
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import executor
import asyncio
import json
import random
import os
import logging

from dotenv import load_dotenv

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Константы
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
OWM_TOKEN = os.getenv("OWM_TOKEN")

# Проверка наличия обязательных переменных окружения
if not TOKEN:
    logger.error("Не найден BOT_TOKEN в переменных окружения")
    exit(1)
if not OWM_TOKEN:
    logger.error("Не найден OWM_TOKEN в переменных окружения")
    exit(1)

# Инициализация бота и диспетчера
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Словарь для хранения последних данных о погоде с ограничением по времени
last_weather = {}  # {user_id: {город: {час: {desc: str, timestamp: float}}}}

# Файл для хранения подписок
SUBSCRIPTIONS_FILE = "subscriptions.json"


# Функция загрузки подписок при старте
def load_subscriptions():
    try:
        with open(SUBSCRIPTIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logger.info(f"Файл {SUBSCRIPTIONS_FILE} не найден или поврежден. Создан новый.")
        return {}


# Функция сохранения подписок
def save_subscriptions(user_subs):
    try:
        with open(SUBSCRIPTIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(user_subs, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Ошибка сохранения JSON: {e}")


# Загружаем подписки при старте
user_subscriptions = load_subscriptions()


# Состояния для работы с ботом
class WeatherForm(StatesGroup):
    waiting_for_city_now = State()
    waiting_for_city_forecast = State()
    waiting_for_city_day = State()
    waiting_for_subscribe_city = State()
    waiting_for_unsubscribe_city = State()


# Создание клавиатуры с местоположением
location_keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
location_keyboard.add(KeyboardButton("📍 Отправить местоположение", request_location=True))


@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer(
        "👋 Привет!\n"
        "Введи одну из команд, чтобы узнать погоду:\n\n"
        "🌦 /Pogoda_now — текущая погода\n"
        "📅 /Pogoda_day — прогноз на день\n"
        "⏳ /pogoda_every_3h — прогноз на 24 часа (каждые 3 часа)\n"
        "📌 /subscribe — подписаться на прогноз погоды\n"
        "🔍 /subs — посмотреть свои подписки\n"
        "❌ /unsubscribe — отписаться от прогноза",
        reply_markup=location_keyboard
    )


# Асинхронная функция для получения погоды
async def fetch_weather(city, endpoint="weather"):
    try:
        url = f'https://api.openweathermap.org/data/2.5/{endpoint}?q={city}&appid={OWM_TOKEN}&units=metric&lang=ru'
        async with session.get(url) as response:
            if response.status == 200:
                return await response.json()
            else:
                logger.warning(f"Ошибка получения данных для {city}: {response.status}")
                return None
    except Exception as e:
        logger.error(f"Ошибка запроса погоды: {e}")
        return None


# Асинхронная функция для получения погоды по координатам
async def fetch_weather_by_coordinates(lat, lon):
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={OWM_TOKEN}&units=metric&lang=ru"
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                description = data["weather"][0]["description"].capitalize()
                temp = data["main"]["temp"]
                wind_speed = data["wind"]["speed"]
                city_name = data.get("name", "Вашем регионе")

                return (
                    f"🌍 Погода в {city_name}:\n"
                    f"🌡 Температура: {temp}°C\n"
                    f"💨 Ветер: {wind_speed} м/с\n"
                    f"☁ {description}\n"
                    f"{generate_weather_description(description, wind_speed, temp)}"
                )
            else:
                logger.warning(f"Ошибка получения данных по координатам: {response.status}")
                return None
    except Exception as e:
        logger.error(f"Ошибка запроса погоды по координатам: {e}")
        return None


# Текущая погода
@dp.message_handler(commands=['Pogoda_now'])
async def get_weather_now(message: Message):
    await message.answer(f"{get_moji()} Введите название города:")
    await WeatherForm.waiting_for_city_now.set()


@dp.message_handler(state=WeatherForm.waiting_for_city_now)
async def receive_weather_now(message: Message, state: FSMContext):
    city = message.text.strip().lower()
    data = await fetch_weather(city)

    if data:
        try:
            temp = data["main"]["temp"]
            desc = data["weather"][0]["description"].capitalize()
            wind_speed = data["wind"]["speed"]
            dt_local = datetime.utcfromtimestamp(data["dt"]) + timedelta(seconds=data["timezone"])
            timezone_offset = data["timezone"]
            weather_text = (
                f"{get_emoji(timezone_offset)} **{city.capitalize()}**\n"
                f"🕒 *Local Time:* {dt_local.strftime('%H:%M')}\n"
                f"---------------------------------\n"
                f"🌡 *Temperature:* {temp}°C\n"
                f"🌫 *Condition:* {desc}\n"
                f"💨 *Wind:* {wind_speed} m/s\n"
                f"{generate_weather_description(desc, wind_speed, temp)}"
            )

            await message.answer(weather_text, parse_mode=ParseMode.MARKDOWN)
        except KeyError as e:
            logger.error(f"Ошибка получения данных из ответа API: {e}")
            await message.answer("❌ Произошла ошибка при обработке данных о погоде.")
    else:
        await message.answer("❌ Ошибка! Город не найден.")

    await state.finish()


# Прогноз каждые 3 часа (на 24 часа)
@dp.message_handler(commands=['pogoda_every_3h'])
async def get_weather_3h(message: Message):
    await message.answer(f"{get_moji()} Введите название города:")
    await WeatherForm.waiting_for_city_forecast.set()


@dp.message_handler(state=WeatherForm.waiting_for_city_forecast)
async def receive_weather_3h(message: Message, state: FSMContext):
    city = message.text.strip().lower()
    data = await fetch_weather(city, "forecast")

    if data:
        try:
            timezone_offset = data["city"]["timezone"]
            forecast_text = (
                f"{get_emoji(timezone_offset)} **{city.capitalize()}** - 24-Hour Forecast\n"
                f"(UTC {timezone_offset // 3600:+d})\n"
                f"---------------------------------\n"
            )

            for forecast in data["list"][:8]:
                dt_local = datetime.strptime(forecast["dt_txt"], "%Y-%m-%d %H:%M:%S") + timedelta(
                    seconds=timezone_offset)
                temp = forecast["main"]["temp"]
                desc = forecast["weather"][0]["description"].capitalize()
                wind_speed = forecast["wind"]["speed"]
                forecast_text += (
                    f"📅 **{dt_local.strftime('%d-%m %H:%M')}**\n"
                    f"🌡 *Temp:* {temp}°C | 🌫 *Cond:* {desc} | 💨 *Wind:* {wind_speed} m/s\n"
                    f"---------------------------------\n"
                )

            await message.answer(forecast_text, parse_mode=ParseMode.MARKDOWN)
        except KeyError as e:
            logger.error(f"Ошибка получения данных из ответа API: {e}")
            await message.answer("❌ Произошла ошибка при обработке данных о погоде.")
    else:
        await message.answer("❌ Ошибка! Город не найден.")

    await state.finish()


def get_moji():
    hour = datetime.now().hour
    emoji_map = {
        range(4, 7): "🌆",
        range(7, 17): "🏙️",
        range(17, 19): "🌇",
        range(19, 22): "🌆",
        range(22, 24): "🌃",
        range(0, 4): "🌃",
    }
    for time_range, emoji in emoji_map.items():
        if hour in time_range:
            return emoji
    return "🌍"  # Возвращаем значение по умолчанию


def get_emoji(timezone_offset):
    user_time = datetime.utcnow() + timedelta(seconds=timezone_offset)
    hour = user_time.hour

    emoji_map = {
        range(4, 7): "🌆",  # Рассвет
        range(7, 17): "🏙️",  # День
        range(17, 19): "🌇",  # Закат
        range(19, 22): "🌆",  # Вечер
        range(22, 24): "🌃",  # Ночь
        range(0, 4): "🌃",  # Поздняя ночь
    }
    for time_range, emoji in emoji_map.items():
        if hour in time_range:
            return emoji
    return "🌍"  # Возвращаем значение по умолчанию


# Прогноз на день
@dp.message_handler(commands=['Pogoda_day'])
async def get_weather_day(message: Message):
    await message.answer(f"{get_moji()} Введите название города:")
    await WeatherForm.waiting_for_city_day.set()


@dp.message_handler(state=WeatherForm.waiting_for_city_day)
async def receive_weather_day(message: Message, state: FSMContext):
    city = message.text.strip().lower()
    data = await fetch_weather(city, "forecast")

    if data:
        try:
            timezone_offset = data["city"]["timezone"]
            today_str = (datetime.utcnow() + timedelta(seconds=timezone_offset)).strftime('%Y-%m-%d')

            daily_temps = []
            wind_speeds = []
            descriptions = {}
            for forecast in data["list"]:
                dt_local = datetime.strptime(forecast["dt_txt"], "%Y-%m-%d %H:%M:%S") + timedelta(
                    seconds=timezone_offset)
                if dt_local.strftime('%Y-%m-%d') == today_str:
                    temp = forecast["main"]["temp"]
                    desc = forecast["weather"][0]["description"].capitalize()
                    daily_temps.append(temp)
                    descriptions[desc] = descriptions.get(desc, 0) + 1
                    wind_speeds.append(forecast["wind"]["speed"])

            if daily_temps:
                max_temp = max(daily_temps)
                avg_temp = round(sum(daily_temps) / len(daily_temps), 1)
                main_desc = max(descriptions, key=descriptions.get)
                max_wind_speed = max(wind_speeds)

                weather_text = (
                    f"{get_emoji(timezone_offset)} **{city.capitalize()}** - Today's Forecast\n"
                    f"---------------------------------\n"
                    f"🌡 *Max Temp:* {max_temp}°C / *Avg Temp:* {avg_temp}°C\n"
                    f"🌫 *Weather:* {main_desc}\n"
                    f"💨 *Max Wind:* {max_wind_speed} m/s\n"
                    f"{generate_weather_description(main_desc, max_wind_speed, max_temp)}"
                )
                await message.answer(weather_text, parse_mode=ParseMode.MARKDOWN)
            else:
                await message.answer("❌ Ошибка! Нет данных на сегодня.")
        except KeyError as e:
            logger.error(f"Ошибка получения данных из ответа API: {e}")
            await message.answer("❌ Произошла ошибка при обработке данных о погоде.")
    else:
        await message.answer("❌ Ошибка! Город не найден.")

    await state.finish()


# Команда подписки
@dp.message_handler(commands=['subscribe'])
async def subscribe(message: types.Message):
    user_id = str(message.from_user.id)  # JSON не поддерживает int в качестве ключей
    if user_id not in user_subscriptions:
        user_subscriptions[user_id] = []  # Создаем список городов для пользователя
        save_subscriptions(user_subscriptions)  # Сразу сохраняем в файл

    await message.answer("📍 Введите название города (или несколько через запятую) для отслеживания:")
    await WeatherForm.waiting_for_subscribe_city.set()


@dp.message_handler(state=WeatherForm.waiting_for_subscribe_city)
async def set_city(message: types.Message, state: FSMContext):
    user_id = str(message.from_user.id)
    cities = [c.strip().lower() for c in message.text.split(",")]

    for city in cities:
        data = await fetch_weather(city)
        if data:
            if city not in user_subscriptions[user_id]:
                user_subscriptions[user_id].append(city)
                await message.answer(f"✅ Город {city.capitalize()} добавлен в подписку!")
                save_subscriptions(user_subscriptions)
            else:
                await message.answer(f"⚠️ {city.capitalize()} уже отслеживается.")
        else:
            await message.answer(f"❌ Город {city.capitalize()} не найден.")

    await state.finish()


@dp.message_handler(commands=['unsubscribe'])
async def unsubscribe_city(message: Message):
    user_id = str(message.from_user.id)

    if user_id not in user_subscriptions or not user_subscriptions[user_id]:
        await message.answer("❌ Вы не подписаны ни на один город.")
        return

    await message.answer(
        "📍 Введите название города, от которого хотите отписаться.\n"
        "Ваши подписки:\n" + "\n".join(c.capitalize() for c in user_subscriptions[user_id])
    )
    await WeatherForm.waiting_for_unsubscribe_city.set()


@dp.message_handler(state=WeatherForm.waiting_for_unsubscribe_city)
async def process_unsubscribe(message: Message, state: FSMContext):
    user_id = str(message.from_user.id)
    city = message.text.strip().lower()

    if city in user_subscriptions.get(user_id, []):
        user_subscriptions[user_id].remove(city)
        if not user_subscriptions[user_id]:  # Если список стал пустым — удалить ключ
            del user_subscriptions[user_id]
        save_subscriptions(user_subscriptions)
        await message.answer(f"✅ Вы отписались от {city.capitalize()}.")
    else:
        await message.answer(f"❌ Вы не подписаны на {city.capitalize()}.")

    await state.finish()


def generate_weather_description(desc, wind_speed, temp):
    # Фразы для температуры
    if temp < -10:
        temp_phrases = [
            "❄️ Боже, как морозно, словно весь мир покрыт льдом!",
            "🥶 Температура ниже -10 — держите шубы крепче, как на штормовом море!",
            "🧣 Холод пробирает до костей, как ледяное прикосновение северных ветров!",
            "❄️ Замерзнуть можно мгновенно — одевайтесь так, будто отправляетесь в Антарктиду!",
            "🥶 Такая стужа способна заморозить даже самые смелые сердца!",
            "🧤 Холода, как у самых суровых морских берегов, не прощают слабости!",
            "❄️ Это холод, как у легендарных северных льдов — берегитесь!",
            "🥶 Мороз бьёт точно, как прицельный выстрел — одевайтесь тепло!",
            "🧣 Каждый шаг словно в ледяной ловушке — шапка, шарф и перчатки обязаны быть с вами!"
        ]
    elif temp < 0:
        temp_phrases = [
            "🥶 Легкий мороз, но достаточно, чтобы напомнить о зиме.",
            "❄️ Прохладно, как на рассвете — оденьтесь получше, чтобы не замерзнуть.",
            "🧤 Температура чуть ниже нуля — пальто и перчатки спасут вас.",
            "❄️ Немного морозно, но это лишь предвестник настоящей зимы.",
            "🥶 Легкий холодок, идеально для уютного чая у камина.",
            "❄️ Морозок, как легкое дуновение зимы, но не забывайте про свитер.",
            "🧤 Прохлада зимних утр требует дополнительного тепла.",
            "🥶 Чуть ниже нуля — просто носите всё, что согревает.",
            "❄️ Небольшой морозок, но он всё равно требует внимания."
        ]
    elif temp < 10:
        temp_phrases = [
            "🌬️ Свежо, как морской бриз, но легкая куртка не помешает.",
            "🧥 Прохладно, как на рассвете у берега — оденьтесь по погоде.",
            "🍂 Освежающе, словно первые волны утра — куртка в плюс.",
            "🌬️ Легкий холодок, который не помешает приключениям.",
            "🧥 Немного прохладно — идеальный повод для стильной куртки.",
            "🍂 Свежесть утреннего порта, где прохлада манит к новым горизонтам.",
            "🌬️ Прохлада, как легкий морской бриз, добавляет бодрости.",
            "🧥 Прохладно, но это лишь приглашение к прогулке.",
            "🍂 Свежесть утреннего моря — не забудьте лёгкий плащ."
        ]
    elif temp < 20:
        temp_phrases = [
            "🌤️ Комфортно, как на палубе в ясный день — время для приключений!",
            "🙂 Погода прекрасная, как морская гладь — идеальна для смелых шагов!",
            "🌿 Тепло, но не жарко — прямо как солнечный день на борту.",
            "🌤️ Идеальные условия, чтобы устремиться к новым горизонтам!",
            "🙂 Погода, словно подарок от моря — наслаждайтесь каждой минутой!",
            "🌿 Тепло, как ласковое прикосновение солнца — время для свершений!",
            "🌤️ Легкая прохлада придает сил для великих открытий!",
            "🙂 Погода балует, словно золотой бриз — просто великолепно!",
            "🌿 Идеальные условия для плавания по волнам судьбы!"
        ]
    else:
        temp_phrases = [
            "☀️ Жарко, как в сердце тропиков — берегитесь перегрева!",
            "🔥 Солнце палит, словно огненное копье — не забывайте пить воду!",
            "😎 Лето во всей красе — солнце, жара и безумные приключения!",
            "☀️ Погода жгучая, как раскалённый металл — лучше искрите прохладой!",
            "🔥 Жарко, как в печке, так что найдите тень и отдыхайте!",
            "😎 Солнце слепит, как алмаз, так что защитите глаза и кожу!",
            "☀️ Температура взлетела, как парус на ветру — пора освежиться!",
            "🔥 Погода раскалённая, как летний шторм, заставляет искать прохладу!",
            "😎 Лето в полном разгаре — солнце жарит, так что берегитесь ожогов!"
        ]

    # Фразы для осадков: дождь или снег. Если ни то, ни другое – универсальные.
    if "дождь" in desc.lower():
        precip_phrases = [
            "🌧️ Ливень, как из ведра, зонт вам точно пригодится!",
            "☔ Дождь за окном – время для уютного чаепития под навесом.",
            "💦 Дождливый день, словно морская волна, заставляет искать укрытие.",
            "🌧️ Небольшой дождик, но достаточно, чтобы промокнуть до нитки!",
            "☔ Дождь моросит, как по расписанию – одевайтесь с умом.",
            "💦 Воды дождя льются, как с неба, так что держитесь подальше от луж.",
            "🌧️ Небесная завеса дождя напоминает: пора обновить зонт.",
            "☔ Дождь окутывает город, как в сказке – найдите своё убежище.",
            "💦 Дождь идет неустанно, словно ритм моря – запаситесь дождевиками!"
        ]
    elif "снег" in desc.lower():
        precip_phrases = [
            "❄️ Снег кружится, как снежные перья – время лепить снеговиков!",
            "☃️ Снежное покрывало, как из сказки – одевайтесь потеплее!",
            "🌨️ Снег падает, словно волшебные хлопья, даря зимнюю сказку!",
            "❄️ Легкий снег, как пушистый ковер, превращает мир в сказку.",
            "☃️ Снежок идет, как мягкий плед – наслаждайтесь зимней магией!",
            "🌨️ Снег, как конфетти, сверкает и украшает мир!",
            "❄️ Снег падает, словно нежные лепестки, создавая зимнюю идиллию.",
            "☃️ Снежная вуаль окутывает всё вокруг – время для зимних приключений!",
            "🌨️ Холодный снег, как кристаллы льда, пробуждает настоящую зимнюю магию!"
        ]
    elif "пасмурно" in desc.lower():
        precip_phrases = [
            "☁️ Тучи сгущаются, как перед хорошей бурей. Надеюсь, дождь не застанет врасплох!",
            "🌫️ Мрачно, как в трюме без света. Не хватает только раскатов грома для атмосферы.",
            "☁️ Серое небо нависло, словно затаившийся шторм. Время задуматься о курсе на солнце!",
            "🌫️ Такое чувство, что солнце решило взять выходной. Надеюсь, оно недолго будет лениться.",
            "☁️ Погода унылая, как потерянное сокровище. Но для приключений это не помеха!",
            "🌫️ Небо хмурое, как разочарованный Зоро. Может, хоть горячий чай скрасит день?",
            "☁️ Всё заволокло облаками, как карту без компаса. Интересно, дождь пойдёт или нет?",
            "🌫️ Море облаков над головой, но главное — держаться курса и не унывать!",
            "☁️ Такая пасмурность обычно предвещает что-то… Или это просто мое воображение?"
        ]
    else:
        precip_phrases = [
            "🌈 Осадков не ожидается, небо чисто, как после шторма.",
            "☀️ Погода сухая и солнечная – идеальна для новых приключений!",
            "🌤️ Никаких осадков, лишь яркое небо и обещание новых горизонтов!",
            "🌞 Ясное небо, как зеркало, отражает мечты о плавании.",
            "✨ Чистое небо, словно карта сокровищ, зовет в путь.",
            "🌟 Небо без облаков – время открывать новые морские маршруты!",
            "💫 Осадков нет, и каждая минута полна возможностей!",
            "🌤️ Светит солнце, как золотой диск – никаких сюрпризов!",
            "☀️ Небо ясное, как обещание удачи – вперед за приключениями!"
        ]

    # Фразы для ветра
    if wind_speed > 15:
        wind_phrases = [
            "💨 Ветер свиреп, как шторм на море – держитесь крепче, друзья!",
            "🌪️ Сильный ветер, словно буря, готов сбить с ног – берегитесь!",
            "🍃 Ветер ревет, как дикое море, не шутите с погодой!",
            "💨 Порывы ветра, как ураган, заставляют крепче держать штурвал!",
            "🌪️ Ветер бушует, как разгневанный океан – лучше не выходить без защиты!",
            "🍃 Ветер свистит, как настоящий шторм – держите шляпы подальше от краев!",
            "💨 Сильный ветер, словно предупреждение от самого моря – будьте осторожны!",
            "🌪️ Ветер так силен, что может унести даже мечты – берегитесь!",
            "🍃 Ветер, как волны на бурном море, не даёт покоя – лучше пристегните вещи!"
        ]
    elif wind_speed > 10:
        wind_phrases = [
            "🌬️ Ветер ощутимый, как лёгкий порыв, добавит свежести в ваш день.",
            "🍃 Ветер играет, слегка развевая волосы – шапка или шарф не помешают.",
            "💨 Ветер заметный, но ещё под контролем – наслаждайтесь дуновением!",
            "🌬️ Довольно ветрено, как морской бриз, так что будьте наготове.",
            "🍃 Ветер дует, как нежное прикосновение – только не переохлаждайтесь.",
            "💨 Ветер колышет, как лёгкая волна – он добавляет свежести без суеты.",
            "🌬️ Ветер присутствует, как тихий шёпот моря, мягко освежая атмосферу.",
            "🍃 Легкий ветерок, как ласковое дуновение, приятно балует вас.",
            "💨 Ветерок нежный, как утренний бриз, дарит чувство легкости."
        ]
    else:
        wind_phrases = [
            "🌀 Ветра почти нет, как спокойное море – идеальные условия для отдыха.",
            "🌫️ Тихо, как в тихой бухте, ветра почти не ощущается – просто наслаждайтесь.",
            "🍃 Минимальный ветер, словно лёгкий шёпот, почти незаметен.",
            "🌀 Практически штиль – спокойствие, как на зеркальной глади моря.",
            "🌫️ Почти нет ветра – условия идеальны для новых открытий.",
            "🍃 Ветра едва уловимый, как тихий утренний бриз, дарит нежность.",
            "🌀 Безветренно, как в тихой гавани – время для спокойного отдыха.",
            "🌫️ Минимальный ветер, почти штиль – идеальная обстановка для размышлений.",
            "🍃 Практически отсутствие ветра – спокойствие и уют на борту."
        ]

    # Выбираем случайные фразы из каждого списка
    temp_phrase = random.choice(temp_phrases)
    precip_phrase = random.choice(precip_phrases)
    wind_phrase = random.choice(wind_phrases)

    return (
        f"{temp_phrase}\n"
        f"{precip_phrase}\n"
        f"{wind_phrase}"
    )


async def fetch_forecast(city):
    """Асинхронная функция для получения прогноза погоды"""
    return await fetch_weather(city, "forecast")


async def weather_monitor():
    while True:
        for user_id, cities in user_subscriptions.items():
            for city in cities:
                data = await fetch_forecast(city)
                if data:
                    timezone_offset = data["city"]["timezone"]
                    now = datetime.utcnow() + timedelta(seconds=timezone_offset)

                    # Инициализируем структуры данных если нужно
                    if user_id not in last_weather:
                        last_weather[user_id] = {}
                    if city not in last_weather[user_id]:
                        last_weather[user_id][city] = {
                            "hourly_forecasts": {},  # Для хранения прогнозов по часам
                            "weather_periods": [],  # Для хранения периодов определенных погодных явлений
                            "sent_notifications": {}  # Для отслеживания отправленных уведомлений
                        }

                    # Массив для хранения всех прогнозов
                    forecasts = []

                    # Собираем все прогнозы на следующие 24 часа
                    for forecast in data["list"]:
                        dt_local = datetime.strptime(forecast["dt_txt"], "%Y-%m-%d %H:%M:%S") + timedelta(
                            seconds=timezone_offset)

                        # Если прогноз в пределах 24 часов от текущего времени
                        if now <= dt_local <= now + timedelta(hours=24):
                            desc = forecast["weather"][0]["description"]
                            wind_speed = forecast["wind"]["speed"]
                            temp = forecast["main"]["temp"]
                            category = categorize_weather(desc)

                            forecast_hour = dt_local.replace(minute=0, second=0, microsecond=0)
                            hour_key = forecast_hour.strftime('%Y%m%d%H')

                            forecast_data = {
                                "datetime": dt_local,
                                "hour_key": hour_key,
                                "desc": desc,
                                "category": category,
                                "wind_speed": wind_speed,
                                "temp": temp
                            }

                            forecasts.append(forecast_data)

                            # Сохраняем прогноз по часам
                            last_weather[user_id][city]["hourly_forecasts"][hour_key] = forecast_data

                    # Если у нас достаточно прогнозов, анализируем их для выявления периодов
                    if forecasts:
                        await analyze_weather_periods(user_id, city, forecasts, now)

        await asyncio.sleep(7200)  # Проверка раз в 3 час


async def analyze_weather_periods(user_id, city, forecasts, now):
    """
    Анализирует прогнозы и выявляет периоды определенных погодных явлений
    """
    # Сортируем прогнозы по времени
    forecasts.sort(key=lambda x: x["datetime"])

    # Находим периоды одинаковой погоды
    periods = []
    current_period = None

    for forecast in forecasts:
        if current_period is None:
            # Начинаем новый период
            current_period = {
                "category": forecast["category"],
                "start_time": forecast["datetime"],
                "end_time": forecast["datetime"],
                "description": forecast["desc"],
                "forecasts": [forecast]
            }
        elif forecast["category"] == current_period["category"]:
            # Продолжаем текущий период
            current_period["end_time"] = forecast["datetime"]
            current_period["forecasts"].append(forecast)
        else:
            # Завершаем текущий период и начинаем новый
            periods.append(current_period)
            current_period = {
                "category": forecast["category"],
                "start_time": forecast["datetime"],
                "end_time": forecast["datetime"],
                "description": forecast["desc"],
                "forecasts": [forecast]
            }

    # Добавляем последний период
    if current_period:
        periods.append(current_period)

    # Обновляем периоды погоды
    last_weather[user_id][city]["weather_periods"] = periods

    # Проверяем паттерны изменения погоды
    await check_weather_patterns(user_id, city, periods, now)


async def check_weather_patterns(user_id, city, periods, now):
    """
    Проверяет паттерны изменения погоды и отправляет содержательные уведомления
    """
    if len(periods) < 2:
        return  # Недостаточно периодов для анализа

    alerts = []

    for i in range(len(periods) - 1):
        current_period = periods[i]
        next_period = periods[i + 1]

        # Формируем уникальный ключ для этой пары периодов
        period_pair_key = f"{current_period['start_time'].strftime('%Y%m%d%H')}_to_{next_period['start_time'].strftime('%Y%m%d%H')}"

        # Проверяем, отправляли ли мы уже уведомление об этом переходе
        if period_pair_key in last_weather[user_id][city]["sent_notifications"]:
            continue

        # Временные рамки для отправки уведомлений
        hours_until_change = (next_period["start_time"] - now).total_seconds() / 3600

        # Уведомляем только о будущих изменениях в пределах 24 часов
        if 0 <= hours_until_change <= 24:
            # Проверяем различные паттерны

            # 1. Прекращение осадков на короткое время
            if (current_period["category"] in ["rain", "snow"] and
                    next_period["category"] not in ["rain", "snow"]):

                # Если есть еще один период после следующего
                if i + 2 < len(periods) and periods[i + 2]["category"] in ["rain", "snow"]:
                    break_duration = (periods[i + 2]["start_time"] - next_period["start_time"]).total_seconds() / 3600

                    # Если перерыв короткий (менее 6 часов)
                    if break_duration <= 6:
                        # Форматируем сообщение о временном перерыве в осадках
                        weather_type = "дождь" if current_period["category"] == "rain" else "снег"
                        start_break = next_period["start_time"].strftime("%d.%m в %H:%M")
                        end_break = periods[i + 2]["start_time"].strftime("%d.%m в %H:%M")

                        msg = (
                            f"⏱️ Прогноз изменения осадков в {city.capitalize()}:\n"
                            f"Ожидается перерыв в осадках ({weather_type}) с {start_break} до {end_break} "
                            f"({int(break_duration)} час{'а' if 1 < break_duration < 5 else 'ов'})\n"
                            f"После перерыва осадки возобновятся."
                        )
                        alerts.append(msg)

                        # Отмечаем, что отправили уведомление для этой пары периодов
                        last_weather[user_id][city]["sent_notifications"][period_pair_key] = True
                        continue

            # 2. Начало осадков
            if (current_period["category"] not in ["rain", "snow"] and
                    next_period["category"] in ["rain", "snow"]):
                # Изменить в коде, где формируются сообщения

                rain_start = next_period["start_time"].strftime("%d.%m в %H:%M")
                weather_type = "дождь" if next_period["category"] == "rain" else "снег"

                # Оцениваем продолжительность осадков
                rain_duration = (next_period["end_time"] - next_period["start_time"]).total_seconds() / 3600

                duration_text = ""
                if 3 > rain_duration > 1:
                    duration_text = f"(кратковременный, около {int(rain_duration)} час{'а' if 1 < rain_duration < 5 else 'ов'})"
                elif 1 >= rain_duration > 0:
                    duration_text = f"(кратковременный, около {int(rain_duration*60)} минут"
                elif rain_duration >= 3:
                    duration_text = f"(продолжительный, около {int(rain_duration)} час{'ов' if rain_duration >= 5 else 'а'})"

                msg = (
                    f"🌧️ Прогноз начала осадков в {city.capitalize()}:\n"
                    f"Ожидается {weather_type} с {rain_start} {duration_text}"
                )
                alerts.append(msg)

                # Отмечаем, что отправили уведомление для этой пары периодов
                last_weather[user_id][city]["sent_notifications"][period_pair_key] = True

            # 3. Резкое изменение температуры между периодами
            curr_avg_temp = sum(f["temp"] for f in current_period["forecasts"]) / len(current_period["forecasts"])
            next_avg_temp = sum(f["temp"] for f in next_period["forecasts"]) / len(next_period["forecasts"])

            temp_diff = next_avg_temp - curr_avg_temp

            if abs(temp_diff) > 6:
                change_time = next_period["start_time"].strftime("%d.%m в %H:%M")
                direction = "потепления" if temp_diff > 0 else "похолодания"

                msg = (
                    f"🌡️ Прогноз резкого изменения температуры в {city.capitalize()}:\n"
                    f"Ожидается {direction} на {abs(temp_diff):.1f}°C с {change_time}"
                )
                alerts.append(msg)

                # Отмечаем, что отправили уведомление для этой пары периодов
                last_weather[user_id][city]["sent_notifications"][period_pair_key] = True

    # Отправляем все уведомления одним сообщением
    if alerts:
        try:
            await bot.send_message(int(user_id), "\n\n".join(alerts))
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения пользователю {user_id}: {e}")


# Вспомогательная функция для категоризации типов погоды
def categorize_weather(desc):
    """
    Группирует похожие типы погоды в категории для более осмысленных сравнений
    """
    desc = desc.lower()

    if any(word in desc for word in ["дождь", "ливень", "гроза"]):
        return "rain"
    elif any(word in desc for word in ["снег", "метель", "снегопад"]):
        return "snow"
    elif any(word in desc for word in ["туман", "мгла"]):
        return "fog"
    elif any(word in desc for word in ["облачно", "пасмурно"]):
        return "cloudy"
    elif any(word in desc for word in ["ясно", "солнечно", "чистое небо"]):
        return "clear"
    else:
        return desc  # Если не попадает ни в одну категорию

@dp.message_handler(commands=["subs"])
async def spisok_subs(message: Message):
    user_id = str(message.from_user.id)
    cities = user_subscriptions.get(user_id, [])

    if cities:
        await message.answer(f"📍 Вы подписаны на эти города:\n" + "\n".join(c.capitalize() for c in cities))
    else:
        await message.answer("❌ Вы пока не подписаны ни на один город.")


@dp.message_handler(content_types=types.ContentType.LOCATION)
async def get_weather_by_location(message: types.Message):
    lat = message.location.latitude
    lon = message.location.longitude

    weather_text = await fetch_weather_by_coordinates(lat, lon)
    if weather_text:
        await message.answer(weather_text)
    else:
        await message.answer("❌ Не удалось получить прогноз погоды. Попробуйте позже.")


# Инициализация HTTP сессии при старте
async def on_startup(dp):
    global session
    session = aiohttp.ClientSession()
    # Запускаем фоновую задачу мониторинга погоды
    asyncio.create_task(weather_monitor())


async def on_shutdown(dp):
    # Закрываем сессию при выключении бота
    if session:
        await session.close()


if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup, on_shutdown=on_shutdown)
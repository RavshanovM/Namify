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
ACCUWEATHER_API_KEY = os.getenv("ACCUWEATHER_API_KEY")

# Проверка наличия обязательных переменных окружения
if not TOKEN:
    logger.error("Не найден BOT_TOKEN в переменных окружения")
    exit(1)
if not ACCUWEATHER_API_KEY:
    logger.error("Не найден ACCUWEATHER_API_KEY в переменных окружения")
    exit(1)

# Инициализация бота и диспетчера
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Словарь для хранения последних данных о погоде с ограничением по времени
last_weather = {}  # {user_id: {город: {час: {desc: str, timestamp: float}}}}

# Файл для хранения подписок
SUBSCRIPTIONS_FILE = "subscriptions.json"

# Словарь для кэширования location key городов (чтобы уменьшить количество запросов)
city_location_keys = {}  # {city_name: location_key}


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


# Функция для получения location key по названию города
async def get_location_key(city):
    if city in city_location_keys:
        return city_location_keys[city]

    try:
        url = f'http://dataservice.accuweather.com/locations/v1/cities/search?apikey={ACCUWEATHER_API_KEY}&q={city}&language=ru'
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                if data and len(data) > 0:
                    # Сохраняем в кэш
                    location_key = data[0]['Key']
                    city_location_keys[city] = location_key
                    return location_key
                else:
                    logger.warning(f"Город {city} не найден")
                    return None
            else:
                logger.warning(f"Ошибка получения location key для {city}: {response.status}")
                return None
    except Exception as e:
        logger.error(f"Ошибка запроса location key: {e}")
        return None


# Асинхронная функция для получения текущей погоды
async def fetch_current_weather(city):
    try:
        location_key = await get_location_key(city)
        if not location_key:
            return None

        url = f'http://dataservice.accuweather.com/currentconditions/v1/{location_key}?apikey={ACCUWEATHER_API_KEY}&language=ru&details=true'
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                if data and len(data) > 0:
                    return data[0]
                else:
                    logger.warning(f"Нет данных о текущей погоде для {city}")
                    return None
            else:
                logger.warning(f"Ошибка получения текущей погоды для {city}: {response.status}")
                return None
    except Exception as e:
        logger.error(f"Ошибка запроса текущей погоды: {e}")
        return None


# Асинхронная функция для получения прогноза на 12 часов
async def fetch_hourly_forecast(city):
    try:
        location_key = await get_location_key(city)
        if not location_key:
            return None

        url = f'http://dataservice.accuweather.com/forecasts/v1/hourly/12hour/{location_key}?apikey={ACCUWEATHER_API_KEY}&language=ru&details=true&metric=true'
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                if data and len(data) > 0:
                    return data
                else:
                    logger.warning(f"Нет данных о часовом прогнозе для {city}")
                    return None
            else:
                logger.warning(f"Ошибка получения часового прогноза для {city}: {response.status}")
                return None
    except Exception as e:
        logger.error(f"Ошибка запроса часового прогноза: {e}")
        return None


# Асинхронная функция для получения прогноза на 5 дней
async def fetch_daily_forecast(city):
    try:
        location_key = await get_location_key(city)
        if not location_key:
            return None

        url = f'http://dataservice.accuweather.com/forecasts/v1/daily/5day/{location_key}?apikey={ACCUWEATHER_API_KEY}&language=ru&details=true&metric=true'
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                if data and 'DailyForecasts' in data:
                    return data
                else:
                    logger.warning(f"Нет данных о дневном прогнозе для {city}")
                    return None
            else:
                logger.warning(f"Ошибка получения дневного прогноза для {city}: {response.status}")
                return None
    except Exception as e:
        logger.error(f"Ошибка запроса дневного прогноза: {e}")
        return None


# Асинхронная функция для получения информации о локации по координатам
async def get_location_by_coordinates(lat, lon):
    try:
        url = f'http://dataservice.accuweather.com/locations/v1/cities/geoposition/search?apikey={ACCUWEATHER_API_KEY}&q={lat},{lon}&language=ru'
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                if data and 'Key' in data:
                    location_key = data['Key']
                    city_name = data.get('LocalizedName', 'Вашем регионе')
                    return location_key, city_name
                else:
                    logger.warning(f"Не удалось получить информацию о локации для координат {lat}, {lon}")
                    return None, None
            else:
                logger.warning(f"Ошибка получения информации о локации: {response.status}")
                return None, None
    except Exception as e:
        logger.error(f"Ошибка запроса информации о локации: {e}")
        return None, None


# Асинхронная функция для получения погоды по координатам
async def fetch_weather_by_coordinates(lat, lon):
    try:
        location_key, city_name = await get_location_by_coordinates(lat, lon)
        if not location_key:
            return None

        url = f'http://dataservice.accuweather.com/currentconditions/v1/{location_key}?apikey={ACCUWEATHER_API_KEY}&language=ru&details=true'
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                if data and len(data) > 0:
                    current = data[0]
                    description = current.get('WeatherText', '')
                    temp = current.get('Temperature', {}).get('Metric', {}).get('Value', 0)
                    wind_speed = current.get('Wind', {}).get('Speed', {}).get('Metric', {}).get('Value', 0)

                    return (
                        f"🌍 Погода в {city_name}:\n"
                        f"🌡 Температура: {temp}°C\n"
                        f"💨 Ветер: {wind_speed} км/ч\n"
                        f"☁ {description}\n"
                        f"{generate_weather_description(description, wind_speed, temp)}"
                    )
                else:
                    logger.warning(f"Не удалось получить текущую погоду для координат {lat}, {lon}")
                    return None
            else:
                logger.warning(f"Ошибка получения текущей погоды: {response.status}")
                return None
    except Exception as e:
        logger.error(f"Ошибка запроса погоды по координатам: {e}")
        return None


# Функция для генерации описания погоды на основе данных
def generate_weather_description(desc, wind_speed, temp):
    """
    Генерирует описание погоды в стиле Нами из One Piece с прямым обращением к пользователю.

    Параметры:
    desc (str): Общее описание погоды (ясно, облачно, дождь и т.д.)
    wind_speed (float): Скорость ветра в м/с
    temp (float): Температура в градусах Цельсия

    Возвращает:
    str: Описание погоды в стиле Нами с обращением к пользователю
    """

    # Описания для разных погодных условий
    descriptions = {
        "ясно": [
            "О! Небо чистое как сокровище! Идеальные условия для навигации. Белль-мере была бы довольна таким днем, не правда ли?",
            "Фууух! Такая прекрасная погода! Эй, ты! Хватит сидеть и глазеть, нам нужно использовать этот попутный ветер!",
            "Мои навигационные инстинкты говорят, что это идеальная погода для нанесения новых карт. Может, поможешь мне с чернилами?"
        ],
        "облачно": [
            "Хммм... эти облака напоминают мне танджеринную рощу на Кокояси. Тебе лучше следить за изменениями давления вместе со мной.",
            "Эти облака... они не опасны, но мне это не нравится. Будь готов быстро действовать, если я скажу!",
            "Обрати внимание на эти кучевые облака! Они предвещают изменение погоды через пару часов. Записал это? Это важно!"
        ],
        "дождь": [
            "Эта буря... Я чувствую её характер! Приготовься! Проверь все окна и двери — я не собираюсь спасать тебя, если промокнешь!",
            "Хах! Этот дождь как слезы морского короля! Эй, ты! Хватит прыгать в лужах, лучше позаботься о своих вещах!",
            "Эта гроза напоминает мне те, что бывали над Арлонг Парком... Не о чем беспокоиться, если будешь следовать моим указаниям!"
        ],
        "гроза": [
            "Я ПРЕДУПРЕЖДАЛА ТЕБЯ! Эта гроза не шутки! Если не будешь слушаться моих советов, пожалеешь!",
            "ЭТО НЕ ОБЫЧНАЯ ГРОЗА! Лучше спрячься дома! Мы справимся, если будем действовать по моему плану!",
            "Ха! Эта гроза ничто по сравнению с тем, что я видела в Гранд Лайн! Но всё равно, НЕ РАССЛАБЛЯЙСЯ! И делай всё, что я говорю!"
        ],
        "снег": [
            "Брр! Этот снег напоминает мне о Драм! Тебе, должно быть, холодно? Лучше надень что-нибудь теплое, пока я не начала злиться!",
            "Этот снегопад... он создаёт идеальные условия для засады. Будь осторожен, когда выходишь на улицу!",
            "Хватит любоваться снежинками! Нам нужно сохранять тепло и следить за направлением ветра! Ты меня слушаешь вообще?"
        ],
        "туман": [
            "Этот туман... он опасен! Будь начеку! Можно запросто попасть в беду или заблудиться!",
            "Хмм... странный туман. Он напоминает мне о Триллер Барке. Не вздумай отходить далеко - заблудишься, как Зоро!",
            "Даже моё искусство навигации бессильно в таком тумане! Лучше останься дома, если не хочешь проблем!"
        ],
        "шторм": [
            "ЭТО НАСТОЯЩИЙ ШТОРМ ГРАНД ЛАЙН! ЗАЙМИ БЕЗОПАСНОЕ ПОЛОЖЕНИЕ! ЭЙ, ПЕРЕСТАНЬ СМЕЯТЬСЯ - ЭТО НЕ ИГРА!",
            "Я ЧУВСТВУЮ ЭТОТ ШТОРМ! ОН КАК ДИКИЙ ЗВЕРЬ! ЛУЧШЕ ПОДГОТОВЬСЯ К ХУДШЕМУ И СЛУШАЙ МОИ СОВЕТЫ!",
            "ВОЛНЫ КАК ГОРЫ! ВЕТЕР КАК АРМИЯ МОРСКИХ КОРОЛЕЙ! НО МЫ СПРАВИМСЯ - Я ЛУЧШИЙ НАВИГАТОР В МИРЕ, ПРОСТО ДЕЛАЙ ЧТО Я ГОВОРЮ!"
        ]
    }

    # Комментарии о ветре
    wind_comments = {
        "слабый": [
            "Ветер едва заметен... тебе придется приложить больше усилий для движения вперёд.",
            "Такой слабый ветерок... может, у тебя есть что-то для ускорения?",
            "Этот ветер не сдвинет даже твою шляпу с головы!"
        ],
        "средний": [
            "Хороший устойчивый ветер - то, что нам нужно!",
            "Этот ветер идеален для нашего курса! Используй его с умом!",
            "Отличный попутный ветер! С ним ты доберёшься куда нужно вдвое быстрее!"
        ],
        "сильный": [
            "Этот ветер может сорвать шляпу с твоей головы! Будь осторожнее!",
            "ТАКОЙ СИЛЬНЫЙ ВЕТЕР! ДЕРЖИСЬ ЗА ЧТО-НИБУДЬ!",
            "Ха! Этот ветер доставит тебя к месту назначения быстрее, чем ты думаешь!"
        ],
        "штормовой": [
            "ВЕТЕР ПРОСТО БЕЗУМНЫЙ! ДАЖЕ МОЙ КЛИМА-ТАКТ НЕ МОЖЕТ ПРОТИВОСТОЯТЬ ЭТОМУ! А У ТЕБЯ И ПОДАВНО НЕТ ШАНСОВ!",
            "ЭТО НАСТОЯЩИЙ ТАЙФУН! НАМ НУЖНО УКРЫТИЕ НЕМЕДЛЕННО!",
            "ДЕРЖИСЬ КРЕПЧЕ! ЭТОТ ВЕТЕР ХОЧЕТ УНЕСТИ ТЕБЯ В НЕИЗВЕСТНОМ НАПРАВЛЕНИИ!"
        ]
    }

    # Комментарии о температуре
    temp_comments = {
        "холодно": [
            "Брр! Даже мои танджерины мёрзнут! Где твой свитер? Не хочу потом лечить тебя от простуды!",
            "Такой холод... Если бы у тебя была шерсть как у Чоппера, было бы проще!",
            "Холодно как в Алабасте ночью! Сделай что-нибудь согревающее, и не смей говорить, что тебе не холодно!"
        ],
        "прохладно": [
            "Немного прохладно. Идеально для тренировки! Что ты стоишь? Движение согреет тебя!",
            "Приятная прохлада. Не хочешь помочь мне с изучением карт?",
            "Хорошая погода для работы. Не время для лени, как думаешь?"
        ],
        "тепло": [
            "Приятное тепло, как в танджериновой роще Белль-мере. Наслаждайся, пока можешь!",
            "Хорошая погода для загара! Только не забудь про солнцезащитный крем, или будешь красным как рак!",
            "Такое приятное тепло... Жаль, что нам нужно заниматься делами вместо отдыха."
        ],
        "жарко": [
            "Эта жара невыносима! Тебе лучше найти прохладительные напитки, и мне принеси тоже!",
            "Жарко как в пустыне Алабасты! Перестань носиться - ты делаешь ещё жарче!",
            "В такую жару даже мои танджерины нуждаются в дополнительном поливе! Может, поможешь мне?"
        ],
        "очень жарко": [
            "СПАСИТЕ! ЭТА ЖАРА УБИВАЕТ МЕНЯ! ПОЧЕМУ Я ЕЩЁ НЕ ПОЛУЧИЛА ЛЕКАРСТВО ОТ ТЕПЛОВОГО УДАРА?! А ТЫ ПОЧЕМУ НЕ СТРАДАЕШЬ?!",
            "НЕВЫНОСИМО! ДАЖЕ МОЙ КЛИМА-ТАКТ ПЕРЕГРЕЛСЯ! НУЖЕН КОНДИЦИОНЕР СЕЙЧАС ЖЕ!",
            "ЭТА ЖАРА ХУЖЕ ЧЕМ АТАКА ЭЙСОМ! МНЕ НУЖЕН ХОЛОДНЫЙ КОКТЕЙЛЬ СЕЙЧАС ЖЕ! И ТЕБЕ СОВЕТУЮ ТОГО ЖЕ!"
        ]
    }

    # Определение категории ветра
    if wind_speed < 2:
        wind_category = "слабый"
    elif wind_speed < 8:
        wind_category = "средний"
    elif wind_speed < 15:
        wind_category = "сильный"
    else:
        wind_category = "штормовой"

    # Определение категории температуры
    if temp < 0:
        temp_category = "холодно"
    elif temp < 15:
        temp_category = "прохладно"
    elif temp < 25:
        temp_category = "тепло"
    elif temp < 32:
        temp_category = "жарко"
    else:
        temp_category = "очень жарко"

    # Получение случайных описаний
    import random

    # Проверка наличия описания погоды
    if desc.lower() in descriptions:
        weather_desc = random.choice(descriptions[desc.lower()])
    else:
        weather_desc = random.choice([
            "Хмм... Странная погода. Даже мои навигационные инстинкты сбиты с толку! А ты что думаешь?",
            "Я никогда не видела ничего подобного даже в Гранд Лайн! Ты хоть понимаешь, насколько это необычно?",
            "Эта погода... она не подчиняется обычным правилам! Будь начеку, если не хочешь неприятностей!"
        ])

    wind_desc = random.choice(wind_comments[wind_category])
    temp_desc = random.choice(temp_comments[temp_category])

    # Обращения к пользователю в начале сообщения
    greetings = [
        "Эй, ты! ",
        "Слушай сюда! ",
        "Внимание! ",
        "Хей! ",
        "Смотри в оба! ",
        "",  # Пустое обращение для разнообразия
        "Ты! Да-да, ты! ",
        "Слушай внимательно! "
    ]

    # Формирование полного описания с обращением к пользователю
    greeting = random.choice(greetings)
    full_description = f"{greeting}{weather_desc} {wind_desc} {temp_desc}"

    # Возможные заключительные фразы
    conclusions = [
        " И не забудь заплатить мне за этот прогноз погоды! Информация стоит денег!",
        " Да, и еще: с тебя 1000 белли за этот метеопрогноз!",
        " Берегись и не забудь мой совет!",
        " Запомни это, если не хочешь проблем!",
        " И не говори потом, что я тебя не предупреждала!",
        "",  # Пустое заключение для разнообразия
        " Я знаю, о чем говорю - я лучший навигатор в мире!",
        " А теперь иди и займись делом!"
    ]

    # Добавление заключительной фразы с вероятностью 70%
    if random.random() < 0.7:
        full_description += random.choice(conclusions)

    return full_description


# Текущая погода
@dp.message_handler(commands=['Pogoda_now'])
async def get_weather_now(message: Message):
    await message.answer(f"{get_moji()} Введите название города:")
    await WeatherForm.waiting_for_city_now.set()


@dp.message_handler(state=WeatherForm.waiting_for_city_now)
async def receive_weather_now(message: Message, state: FSMContext):
    city = message.text.strip().lower()
    data = await fetch_current_weather(city)

    if data:
        try:
            temp = data['Temperature']['Metric']['Value']
            desc = data['WeatherText']
            wind_speed = data['Wind']['Speed']['Metric']['Value']

            # Получаем местное время из временной метки наблюдения
            observation_time = datetime.strptime(data['LocalObservationDateTime'], "%Y-%m-%dT%H:%M:%S%z")
            local_time = observation_time.strftime('%H:%M')

            is_day = data.get('IsDayTime', True)
            emoji = "🏙️" if is_day else "🌃"

            weather_text = (
                f"{emoji} **{city.capitalize()}**\n"
                f"🕒 *Local Time:* {local_time}\n"
                f"---------------------------------\n"
                f"🌡 *Temperature:* {temp}°C\n"
                f"🌫 *Condition:* {desc}\n"
                f"💨 *Wind:* {wind_speed} км/ч\n"
                f"{generate_weather_description(desc, wind_speed, temp)}"
            )

            await message.answer(weather_text, parse_mode=ParseMode.MARKDOWN)
        except KeyError as e:
            logger.error(f"Ошибка получения данных из ответа API: {e}")
            await message.answer("❌ Произошла ошибка при обработке данных о погоде.")
    else:
        await message.answer("❌ Ошибка! Город не найден.")

    await state.finish()


# Прогноз каждые 3 часа (на 12 часов)
@dp.message_handler(commands=['pogoda_every_3h'])
async def get_weather_3h(message: Message):
    await message.answer(f"{get_moji()} Введите название города:")
    await WeatherForm.waiting_for_city_forecast.set()


@dp.message_handler(state=WeatherForm.waiting_for_city_forecast)
async def receive_weather_3h(message: Message, state: FSMContext):
    city = message.text.strip().lower()
    data = await fetch_hourly_forecast(city)

    if data:
        try:
            forecast_text = (
                f"🌍 **{city.capitalize()}** - 12-Hour Forecast\n"
                f"---------------------------------\n"
            )

            # Выбираем каждые 3 часа прогноза (индексы 0, 3, 6, 9)
            selected_forecasts = [data[i] for i in range(0, min(12, len(data)), 3)]

            for forecast in selected_forecasts:
                dt_local = datetime.strptime(forecast['DateTime'], "%Y-%m-%dT%H:%M:%S%z")
                temp = forecast['Temperature']['Value']
                desc = forecast['IconPhrase']
                wind_speed = forecast['Wind']['Speed']['Value']
                is_day = forecast.get('IsDaylight', True)
                emoji = "☀️" if is_day else "🌙"

                forecast_text += (
                    f"{emoji} **{dt_local.strftime('%d-%m %H:%M')}**\n"
                    f"🌡 *Temp:* {temp}°C | 🌫 *Cond:* {desc} | 💨 *Wind:* {wind_speed} км/ч\n"
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


# Прогноз на день
@dp.message_handler(commands=['Pogoda_day'])
async def get_weather_day(message: Message):
    await message.answer(f"{get_moji()} Введите название города:")
    await WeatherForm.waiting_for_city_day.set()


@dp.message_handler(state=WeatherForm.waiting_for_city_day)
async def receive_weather_day(message: Message, state: FSMContext):
    city = message.text.strip().lower()
    data = await fetch_daily_forecast(city)

    if data:
        try:
            # Берем только прогноз на сегодня
            today_forecast = data['DailyForecasts'][0]

            # Получаем дату
            date = datetime.strptime(today_forecast['Date'], "%Y-%m-%dT%H:%M:%S%z").strftime('%d.%m.%Y')

            # Температуры
            min_temp = today_forecast['Temperature']['Minimum']['Value']
            max_temp = today_forecast['Temperature']['Maximum']['Value']
            avg_temp = (min_temp + max_temp) / 2

            # Описание дня и ночи
            day_desc = today_forecast['Day']['IconPhrase']
            night_desc = today_forecast['Night']['IconPhrase']

            # Ветер (берем максимальный)
            day_wind = today_forecast['Day']['Wind']['Speed']['Value']
            night_wind = today_forecast['Night']['Wind']['Speed']['Value']
            max_wind = max(day_wind, night_wind)

            # Вероятность осадков
            day_precip_prob = today_forecast['Day'].get('PrecipitationProbability', 0)
            night_precip_prob = today_forecast['Night'].get('PrecipitationProbability', 0)

            weather_text = (
                f"🌍 **{city.capitalize()}** - Прогноз на {date}\n"
                f"---------------------------------\n"
                f"🌡 *Температура:* от {min_temp}°C до {max_temp}°C (в среднем {avg_temp:.1f}°C)\n"
                f"☀️ *Днем:* {day_desc} (вероятность осадков: {day_precip_prob}%)\n"
                f"🌙 *Ночью:* {night_desc} (вероятность осадков: {night_precip_prob}%)\n"
                f"💨 *Максимальный ветер:* {max_wind} км/ч\n"
                f"{generate_weather_description(day_desc, max_wind, max_temp)}"
            )

            await message.answer(weather_text, parse_mode=ParseMode.MARKDOWN)
        except KeyError as e:
            logger.error(f"Ошибка получения данных из ответа API: {e}")
            await message.answer("❌ Произошла ошибка при обработке данных о погоде.")
    else:
        await message.answer("❌ Ошибка! Город не найден.")

    await state.finish()

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
        # Проверяем существование города через получение location key
        location_key = await get_location_key(city)
        if location_key:
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


# Категоризация типов погоды для AccuWeather
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


async def weather_monitor():
    while True:
        for user_id, cities in user_subscriptions.items():
            for city in cities:
                # Получаем данные о текущей погоде и прогноз на ближайшие часы
                current_data = await fetch_current_weather(city)
                forecast_data = await fetch_hourly_forecast(city)

                if current_data and forecast_data:
                    # Инициализируем структуры данных если нужно
                    if user_id not in last_weather:
                        last_weather[user_id] = {}
                    if city not in last_weather[user_id]:
                        last_weather[user_id][city] = {
                            "hourly_forecasts": {},  # Для хранения прогнозов по часам
                            "weather_periods": [],  # Для хранения периодов определенных погодных явлений
                            "sent_notifications": {}  # Для отслеживания отправленных уведомлений
                        }

                    # Текущее время
                    now = datetime.now()

                    # Анализируем прогнозы
                    forecasts = []
                    for forecast in forecast_data:
                        dt_local = datetime.strptime(forecast['DateTime'], "%Y-%m-%dT%H:%M:%S%z")
                        dt_local = dt_local.replace(tzinfo=None)  # Убираем часовой пояс для сравнения

                        desc = forecast['IconPhrase']
                        wind_speed = forecast['Wind']['Speed']['Value']
                        temp = forecast['Temperature']['Value']
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

        await asyncio.sleep(7200)  # Проверка раз в 2 часа


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

                rain_start = next_period["start_time"].strftime("%d.%m в %H:%M")
                weather_type = "дождь" if next_period["category"] == "rain" else "снег"

                # Оцениваем продолжительность осадков
                rain_duration = (next_period["end_time"] - next_period["start_time"]).total_seconds() / 3600

                duration_text = ""
                if 3 > rain_duration > 1:
                    duration_text = f"(кратковременный, около {int(rain_duration)} час{'а' if 1 < rain_duration < 5 else 'ов'})"
                elif 1 >= rain_duration > 0:
                    duration_text = f"(кратковременный, около {int(rain_duration * 60)} минут)"
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

            # 4. Сильный ветер
            avg_wind_speed_current = sum(f["wind_speed"] for f in current_period["forecasts"]) / len(
                current_period["forecasts"])
            avg_wind_speed_next = sum(f["wind_speed"] for f in next_period["forecasts"]) / len(next_period["forecasts"])

            # Если ветер усилится до значительного уровня
            if avg_wind_speed_next > 15 and avg_wind_speed_next > avg_wind_speed_current * 1.5:
                change_time = next_period["start_time"].strftime("%d.%m в %H:%M")

                msg = (
                    f"💨 Предупреждение о ветре в {city.capitalize()}:\n"
                    f"С {change_time} ожидается усиление ветра до {avg_wind_speed_next:.1f} км/ч\n"
                    f"Будьте осторожны на улице!"
                )
                alerts.append(msg)

                # Отмечаем, что отправили уведомление
                last_weather[user_id][city]["sent_notifications"][period_pair_key] = True

            # 5. Предупреждение о тумане
            if next_period["category"] == "fog" and current_period["category"] != "fog":
                fog_time = next_period["start_time"].strftime("%d.%m в %H:%M")

                msg = (
                    f"🌫️ Предупреждение о тумане в {city.capitalize()}:\n"
                    f"С {fog_time} ожидается туман. Видимость будет ограничена.\n"
                    f"Будьте внимательны на дорогах!"
                )
                alerts.append(msg)

                # Отмечаем, что отправили уведомление
                last_weather[user_id][city]["sent_notifications"][period_pair_key] = True

    # Отправляем все уведомления одним сообщением
    if alerts:
        try:
            await bot.send_message(int(user_id), "\n\n".join(alerts))
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения пользователю {user_id}: {e}")


# Периодическая отправка прогноза погоды подписчикам
async def send_daily_forecast():
    """
    Отправляет ежедневный прогноз погоды всем подписчикам утром (8:00)
    """
    while True:
        # Получаем текущее время
        now = datetime.now()

        # Рассчитываем время до 8 утра следующего дня
        target_time = now.replace(hour=8, minute=0, second=0, microsecond=0)
        if now.hour >= 8:
            target_time += timedelta(days=1)

        # Вычисляем сколько секунд осталось ждать
        seconds_to_wait = (target_time - now).total_seconds()

        # Ждем до целевого времени
        await asyncio.sleep(seconds_to_wait)

        # Отправляем прогноз каждому подписчику
        for user_id, cities in user_subscriptions.items():
            for city in cities:
                try:
                    # Получаем прогноз на день
                    data = await fetch_daily_forecast(city)

                    if data:
                        # Берем только прогноз на сегодня
                        today_forecast = data['DailyForecasts'][0]

                        # Получаем дату
                        date = datetime.strptime(today_forecast['Date'], "%Y-%m-%dT%H:%M:%S%z").strftime('%d.%m.%Y')

                        # Температуры
                        min_temp = today_forecast['Temperature']['Minimum']['Value']
                        max_temp = today_forecast['Temperature']['Maximum']['Value']

                        # Описание дня и ночи
                        day_desc = today_forecast['Day']['IconPhrase']
                        night_desc = today_forecast['Night']['IconPhrase']

                        # Ветер
                        day_wind = today_forecast['Day']['Wind']['Speed']['Value']
                        night_wind = today_forecast['Night']['Wind']['Speed']['Value']

                        # Вероятность осадков
                        day_precip_prob = today_forecast['Day'].get('PrecipitationProbability', 0)
                        night_precip_prob = today_forecast['Night'].get('PrecipitationProbability', 0)

                        weather_text = (
                            f"☀️ Доброе утро! Прогноз погоды на сегодня, {date}\n"
                            f"🌍 **{city.capitalize()}**\n"
                            f"---------------------------------\n"
                            f"🌡 *Температура:* от {min_temp}°C до {max_temp}°C\n"
                            f"☀️ *Днем:* {day_desc} (вероятность осадков: {day_precip_prob}%)\n"
                            f"🌙 *Ночью:* {night_desc} (вероятность осадков: {night_precip_prob}%)\n"
                            f"💨 *Ветер:* днем - {day_wind} км/ч, ночью - {night_wind} км/ч\n"
                            f"{generate_weather_description(day_desc, day_wind, max_temp)}"
                        )

                        await bot.send_message(int(user_id), weather_text, parse_mode=ParseMode.MARKDOWN)
                except Exception as e:
                    logger.error(f"Ошибка отправки ежедневного прогноза пользователю {user_id} для города {city}: {e}")

        # Если отправка заняла время, корректируем следующий цикл
        await asyncio.sleep(60)  # Защита от случайного выполнения цикла слишком быстро


@dp.message_handler(commands=['help'])
async def help_command(message: types.Message):
    """Отправляет справочную информацию о боте"""
    help_text = (
        "🌦 **Погодный бот - справка по командам**\n\n"
        "• /start - Начало работы и главное меню\n"
        "• /Pogoda_now - Узнать текущую погоду в указанном городе\n"
        "• /Pogoda_day - Прогноз погоды на день\n"
        "• /pogoda_every_3h - Прогноз каждые 3 часа на ближайшие 12 часов\n"
        "• /subscribe - Подписаться на обновления погоды\n"
        "• /subs - Посмотреть свои текущие подписки\n"
        "• /unsubscribe - Отписаться от обновлений погоды\n"
        "• /help - Показать эту справку\n\n"
        "📱 Вы также можете отправить свое текущее местоположение, чтобы получить прогноз погоды для вашего района."
    )
    await message.answer(help_text, parse_mode=ParseMode.MARKDOWN)


@dp.message_handler()
async def process_text_message(message: types.Message):
    """Обрабатывает текстовые сообщения, не связанные с командами"""
    city = message.text.strip().lower()

    # Проверяем, является ли текст названием города
    location_key = await get_location_key(city)

    if location_key:
        # Если это название города, отправляем текущую погоду
        data = await fetch_current_weather(city)

        if data:
            try:
                temp = data['Temperature']['Metric']['Value']
                desc = data['WeatherText']
                wind_speed = data['Wind']['Speed']['Metric']['Value']

                # Получаем местное время из временной метки наблюдения
                observation_time = datetime.strptime(data['LocalObservationDateTime'], "%Y-%m-%dT%H:%M:%S%z")
                local_time = observation_time.strftime('%H:%M')

                is_day = data.get('IsDayTime', True)
                emoji = "🏙️" if is_day else "🌃"

                weather_text = (
                    f"{emoji} **{city.capitalize()}**\n"
                    f"🕒 *Local Time:* {local_time}\n"
                    f"---------------------------------\n"
                    f"🌡 *Temperature:* {temp}°C\n"
                    f"🌫 *Condition:* {desc}\n"
                    f"💨 *Wind:* {wind_speed} км/ч\n"
                    f"{generate_weather_description(desc, wind_speed, temp)}"
                )

                await message.answer(weather_text, parse_mode=ParseMode.MARKDOWN)
            except KeyError as e:
                logger.error(f"Ошибка получения данных из ответа API: {e}")
                await message.answer("❌ Произошла ошибка при обработке данных о погоде.")
        else:
            await message.answer("❌ Ошибка! Не удалось получить информацию о погоде.")
    else:
        # Если это не название города, отправляем подсказку
        await message.answer(
            "🤔 Я не понимаю ваш запрос. Используйте команды:\n"
            "/Pogoda_now - текущая погода\n"
            "/Pogoda_day - прогноз на день\n"
            "/pogoda_every_3h - прогноз каждые 3 часа\n"
            "/help - справка по всем командам"
        )


# Инициализация HTTP сессии при старте
async def on_startup(dp):
    global session
    session = aiohttp.ClientSession()

    # Запускаем фоновые задачи
    asyncio.create_task(weather_monitor())
    asyncio.create_task(send_daily_forecast())

    logger.info("Бот запущен и готов к работе")


async def on_shutdown(dp):
    # Закрываем сессию при выключении бота
    if session:
        await session.close()
    logger.info("Бот остановлен")


if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup, on_shutdown=on_shutdown)
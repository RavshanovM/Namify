from datetime import datetime, timedelta
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
import requests
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message, ParseMode
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import executor
import asyncio
import json
import random
# Константы
TOKEN = "7519852063:AAHT4lEHc1xc2JZFeCCiD3n5Sm1ZcH3cR8w"
OWM_TOKEN = "8718b212f5b86944c0236f98618c961c"

# Инициализация бота и диспетчера
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)
last_weather = {}  # {user_id: {город: {час: описание}}}

# Файл для хранения подписок
SUBSCRIPTIONS_FILE = "subscriptions.json"

# Функция загрузки подписок при старте
def load_subscriptions():
    try:
        with open(SUBSCRIPTIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

# Функция сохранения подписок
def save_subscriptions():
    try:
        with open(SUBSCRIPTIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(user_subscriptions, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"Ошибка сохранения JSON: {e}")

# Загружаем подписки при старте
user_subscriptions = load_subscriptions()

# Состояния для ввода города
class WeatherForm(StatesGroup):
    waiting_for_city_now = State()
    waiting_for_city_forecast = State()
    waiting_for_city_day = State()

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer(
        "👋 Привет!\n"
        "Введи одну из команд, чтобы узнать погоду:\n\n"
        "🌦 /Pogoda_now — текущая погода\n"
        "📅 /Pogoda_day — прогноз на день\n"
        "⏳ /pogoda_every_3h — прогноз на 24 часа (каждые 3 часа)",
        reply_markup = location_keyboard
    )

async def fetch_weather(city, endpoint="weather"):
    url = f'https://api.openweathermap.org/data/2.5/{endpoint}?q={city}&appid={OWM_TOKEN}&units=metric&lang=ru'
    response = requests.get(url)
    return response.json() if response.status_code == 200 else None

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
    list_temp = []
    if data:
        timezone_offset = data["city"]["timezone"]
        forecast_text = (
            f"{get_emoji(timezone_offset)} **{city.capitalize()}** - 24-Hour Forecast\n"
            f"(UTC {timezone_offset // 3600:+d})\n"
            f"---------------------------------\n"
        )

        for forecast in data["list"][:8]:
            dt_local = datetime.strptime(forecast["dt_txt"], "%Y-%m-%d %H:%M:%S") + timedelta(seconds=timezone_offset)
            temp = forecast["main"]["temp"]
            desc = forecast["weather"][0]["description"].capitalize()
            wind_speed = forecast["wind"]["speed"]
            list_temp.append(temp)
            forecast_text += (
                f"📅 **{dt_local.strftime('%d-%m %H:%M')}**\n"
                f"🌡 *Temp:* {temp}°C | 🌫 *Cond:* {desc} | 💨 *Wind:* {wind_speed} m/s\n"
                f"---------------------------------\n"
            )

        await message.answer(forecast_text, parse_mode=ParseMode.MARKDOWN)
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
def get_emoji(timezone_offset):
    user_time = datetime.utcnow() + timedelta(seconds=timezone_offset)
    hour = user_time.hour

    emoji_map = {
        range(4, 7): "🌆",   # Рассвет
        range(7, 17): "🏙️",  # День
        range(17, 19): "🌇",  # Закат
        range(19, 22): "🌆",  # Вечер
        range(22, 24): "🌃",  # Ночь
        range(0, 4): "🌃",    # Поздняя ночь
    }
    for time_range, emoji in emoji_map.items():
        if hour in time_range:
            return emoji
    return "❓"  # На случай ошибки
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
        timezone_offset = data["city"]["timezone"]
        today_str = (datetime.utcnow() + timedelta(seconds=timezone_offset)).strftime('%Y-%m-%d')

        list_temp = []
        daily_temps = []
        wind_speeds = []
        descriptions = {}
        for forecast in data["list"]:
            dt_local = datetime.strptime(forecast["dt_txt"], "%Y-%m-%d %H:%M:%S") + timedelta(seconds=timezone_offset)
            if dt_local.strftime('%Y-%m-%d') == today_str:
                temp = forecast["main"]["temp"]
                desc = forecast["weather"][0]["description"].capitalize()
                daily_temps.append(temp)
                descriptions[desc] = descriptions.get(desc, 0) + 1
                wind_speeds.append(forecast["wind"]["speed"])
                list_temp.append(temp)

        if daily_temps:
            max_temp = max(list_temp)
            avg_temp = round(sum(daily_temps) / len(daily_temps), 1)
            main_desc = max(descriptions, key=descriptions.get)
            max_wind_speed = max(wind_speeds)
            timezone_offset = data["city"]["timezone"]
            weather_text = (
                f"{get_emoji(timezone_offset)} **{city.capitalize()}** - Today's Forecast\n"
                f"---------------------------------\n"
                f"🌡 *Max Temp:*{max_temp}°C / *Avg Temp:* {avg_temp}°C\n"
                f"🌫 *Weather:* {main_desc}\n"
                f"💨 *Max Wind:* {max_wind_speed} m/s\n"
                f"{generate_weather_description(main_desc, max_wind_speed, max_temp)}"
            )
            await message.answer(weather_text, parse_mode=ParseMode.MARKDOWN)
        else:
            await message.answer("❌ Ошибка! Нет данных на сегодня.")
    else:
        await message.answer("❌ Ошибка! Город не найден.")

    await state.finish()

async def fetch_forecast(city):
    url = f'https://api.openweathermap.org/data/2.5/forecast?q={city}&appid={OWM_TOKEN}&units=metric&lang=ru'
    response = requests.get(url)
    return response.json() if response.status_code == 200 else None

waiting_for_city = set()  # Храним ID пользователей, которые вводят город

# Команда подписки
@dp.message_handler(commands=['subscribe'])
async def subscribe(message: types.Message):
    user_id = str(message.from_user.id)  # JSON не поддерживает int в качестве ключей
    if user_id not in user_subscriptions:
        user_subscriptions[user_id] = []  # Создаем список городов для пользователя
        save_subscriptions()  # Сразу сохраняем в файл

    await message.answer("📍 Введите название города (или несколько через запятую) для отслеживания:")
    waiting_for_city.add(user_id)

@dp.message_handler(lambda message: str(message.from_user.id) in waiting_for_city)
async def set_city(message: types.Message):
    user_id = str(message.from_user.id)
    cities = [c.strip().lower() for c in message.text.split(",")]

    for city in cities:
        data = await fetch_forecast(city)
        if data:
            if city not in user_subscriptions[user_id]:
                user_subscriptions[user_id].append(city)
                await message.answer(f"✅ Город {city.capitalize()} добавлен в подписку!")
                save_subscriptions()  # Теперь вызываем после обновления подписок
            else:
                await message.answer(f"⚠️ {city.capitalize()} уже отслеживается.")
        else:
            await message.answer(f"❌ Город {city.capitalize()} не найден.")

    waiting_for_city.discard(user_id)
# Фоновая проверка погоды

waiting_for_unsub = set()

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
    waiting_for_unsub.add(user_id)  # Добавляем в ожидание ввода


@dp.message_handler(lambda message: str(message.from_user.id) in waiting_for_unsub)
async def process_unsubscribe(message: Message):
    user_id = str(message.from_user.id)
    city = message.text.strip().lower()  # Приводим к нижнему регистру для一致ности

    if city in user_subscriptions.get(user_id, []):
        user_subscriptions[user_id].remove(city)
        if not user_subscriptions[user_id]:  # Если список стал пустым — удалить ключ
            del user_subscriptions[user_id]
        save_subscriptions()  # Сохранить изменения
        await message.answer(f"✅ Вы отписались от {city.capitalize()}.")
    else:
        await message.answer(f"❌ Вы не подписаны на {city.capitalize()}.")

    waiting_for_unsub.discard(user_id)  # Убираем из списка ожидания


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
    if "дождь" in desc:
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
    elif "снег" in desc:
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
    elif "Пасмурно" in desc:
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


async def weather_monitor():
    while True:
        for user_id, cities in user_subscriptions.items():
            for city in cities:
                data = await fetch_forecast(city)
                if data:
                    timezone_offset = data["city"]["timezone"]
                    now = datetime.utcnow() + timedelta(seconds=timezone_offset)
                    next_hours = [now + timedelta(hours=i) for i in range(1, 7)]

                    alerts = []
                    for forecast in data["list"]:
                        dt_local = datetime.strptime(forecast["dt_txt"], "%Y-%m-%d %H:%M:%S") + timedelta(seconds=timezone_offset)
                        if dt_local in next_hours:
                            desc = forecast["weather"][0]["description"]
                            wind_speed = forecast["wind"]["speed"]
                            temp = forecast["main"]["temp"]

                            # Если погода уже записана, но сообщение дублируется, все равно отправляем
                            if user_id not in last_weather:
                                last_weather[user_id] = {}
                            if city not in last_weather[user_id]:
                                last_weather[user_id][city] = {}

                            alert_msg = generate_weather_description(desc, wind_speed, temp)
                            alerts.append(alert_msg)

                            # Записываем прогноз, чтобы не отправлять совсем дублирующие сообщения в течение часа
                            last_weather[user_id][city][dt_local.hour] = desc

                    if alerts:
                        await bot.send_message(user_id, "\n".join(alerts))

        await asyncio.sleep(3600)  # Проверка раз в час



@dp.message_handler(commands=["subs"])
async def spisok_subs(message: Message):
    user_id = str(message.from_user.id)  # Приводим к str, как в user_subscriptions
    cities = user_subscriptions.get(user_id, [])  # Получаем список городов или []

    if cities:
        await message.answer(f"📍 Вы подписаны на эти города:\n" + "\n".join(c.capitalize() for c in cities))
    else:
        await message.answer("❌ Вы пока не подписаны ни на один город.")


location_keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
location_keyboard.add(KeyboardButton("📍 Отправить местоположение", request_location=True))


@dp.message_handler(content_types=types.ContentType.LOCATION)
async def get_weather_by_location(message: types.Message):
    lat = message.location.latitude
    lon = message.location.longitude

    weather_data = fetch_weather_by_coordinates(lat, lon)
    if weather_data:
        await message.answer(weather_data)
    else:
        await message.answer("❌ Не удалось получить прогноз погоды. Попробуйте позже.")


def fetch_weather_by_coordinates(lat, lon):
    url = f"http://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={OWM_TOKEN}&units=metric&lang=ru"
    response = requests.get(url)

    if response.status_code == 200:
        data = response.json()
        description = data["weather"][0]["description"].capitalize()
        temp = data["main"]["temp"]
        wind_speed = data["wind"]["speed"]

        return f"🌍 Погода в вашем регионе:\n🌡 Температура: {temp}°C\n💨 Ветер: {wind_speed} м/с\n☁ {description}\n{generate_weather_description(description, wind_speed, temp)}"
    return None


# Запуск фоновой задачи
async def on_startup(_):
    asyncio.create_task(weather_monitor())

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
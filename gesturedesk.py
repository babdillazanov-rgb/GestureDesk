"""
GestureDesk - ГЛАВНАЯ ПРОГРАММА
=================================
Жесты + Голос + Веб-панель работают одновременно!

Установка:
    pip install flask

Запуск:
    python gesturedesk.py

Затем открой в браузере:
    http://localhost:5000
"""

import cv2
import mediapipe as mp
import pyautogui
import subprocess
import webbrowser
import speech_recognition as sr
import threading
import time
import urllib.parse
import json
from flask import Flask, jsonify
from datetime import datetime

# ══════════════════════════════════════════
#  НАСТРОЙКИ
# ══════════════════════════════════════════

LANGUAGE       = "ru-RU"
GESTURE_COOLDOWN = 1.2
SCREENSHOT_COOLDOWN = 5.0
last_screenshot_time = 0

# ── Режим врача ──
DOCTOR_MODE = False   # False = обычный, True = режим врача

pyautogui.FAILSAFE = True

# ══════════════════════════════════════════
#  КОМАНДЫ РЕЖИМА ВРАЧА
#  Только безопасные — листание, зум, пауза
# ══════════════════════════════════════════

DOCTOR_COMMANDS = [
    # Листание снимков/слайдов
    (["следующий снимок", "следующий", "дальше", "вперёд"],
        lambda: pyautogui.press('right'),              "📋 Следующий снимок"),

    (["предыдущий снимок", "предыдущий", "назад"],
        lambda: pyautogui.press('left'),               "📋 Предыдущий снимок"),

    # Зум
    (["увеличить", "увеличь", "приблизить", "приближение"],
        lambda: pyautogui.hotkey('ctrl', '+'),         "🔍 Увеличить"),

    (["уменьшить", "уменьши", "отдалить"],
        lambda: pyautogui.hotkey('ctrl', '-'),         "🔍 Уменьшить"),

    (["исходный размер", "сбросить зум", "нормальный размер"],
        lambda: pyautogui.hotkey('ctrl', '0'),         "🔍 Исходный размер"),

    # Пауза / стоп
    (["пауза", "стоп", "остановить"],
        lambda: pyautogui.press('space'),              "⏸ Пауза"),

    (["полный экран", "на весь экран"],
        lambda: pyautogui.press('f11'),                "🖥 Полный экран"),

    (["прокрутить вниз", "вниз"],
        lambda: pyautogui.press('pagedown'),           "⬇️ Вниз"),

    (["прокрутить вверх", "вверх"],
        lambda: pyautogui.press('pageup'),             "⬆️ Вверх"),

    # Переключение режима
    (["обычный режим", "выключи режим врача", "стандартный режим"],
        lambda: toggle_doctor_mode(),                  "🔄 Обычный режим"),
]

# Жесты в режиме врача
DOCTOR_GESTURES = {
    0: (lambda: pyautogui.press('space'),   "⏸ Пауза"),
    1: (lambda: pyautogui.press('left'),    "📋 Предыдущий"),
    2: (lambda: pyautogui.press('right'),   "📋 Следующий"),
    3: (lambda: pyautogui.hotkey('ctrl', '+'), "🔍 Увеличить"),
    4: (lambda: pyautogui.hotkey('ctrl', '-'), "🔍 Уменьшить"),
    5: (lambda: pyautogui.press('f11'),     "🖥 Полный экран"),
}

def toggle_doctor_mode():
    global DOCTOR_MODE
    DOCTOR_MODE = not DOCTOR_MODE
    mode = "🏥 РЕЖИМ ВРАЧА" if DOCTOR_MODE else "💻 Обычный режим"
    log("🔄", mode)

# ══════════════════════════════════════════
#  ОБЩИЙ ЛОГ (отображается на экране камеры)
# ══════════════════════════════════════════

last_action   = ""
action_source = ""
log_lines     = []
log_lock      = threading.Lock()

# Общие данные для веб-панели
state = {
    "total": 0,
    "gestures": 0,
    "voices": 0,
    "fingers": -1,
    "log": []
}

def log(source, message, is_gesture=None):
    """Добавляет запись в лог и обновляет экран и веб-панель."""
    global last_action, action_source
    last_action   = message
    action_source = source

    is_gest = is_gesture if is_gesture is not None else ("👋" in source)
    now = datetime.now().strftime("%H:%M:%S")

    with log_lock:
        log_lines.append(f"{source}: {message}")
        if len(log_lines) > 5:
            log_lines.pop(0)

        state["total"] += 1
        if is_gest:
            state["gestures"] += 1
        else:
            state["voices"] += 1

        state["log"].insert(0, {
            "icon":    source,
            "command": message,
            "type":    "жест" if is_gest else "голос",
            "time":    now
        })
        if len(state["log"]) > 50:
            state["log"].pop()

    print(f"{source} {message}")
    show_overlay(message)


# ══════════════════════════════════════════
#  ВЕБ-СЕРВЕР (Flask — отдаёт данные панели)
# ══════════════════════════════════════════

flask_app = Flask(__name__)

@flask_app.route("/")
def index():
    """Отдаёт dashboard.html напрямую."""
    import os
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h2>Положи dashboard.html в ту же папку что и gesturedesk.py</h2>", 404

@flask_app.route("/api/state")
def api_state():
    with log_lock:
        return jsonify(state)

def run_flask():
    flask_app.run(port=5000, debug=False, use_reloader=False)



# ══════════════════════════════════════════
#  КОМАНДЫ (общие для жестов и голоса)
# ══════════════════════════════════════════

def open_url(url):
    subprocess.Popen(f"start {url}", shell=True)

def open_app(app):
    subprocess.Popen(app, shell=True)

def show_overlay(text):
    """Показывает уведомление Windows в правом нижнем углу."""
    def _show():
        try:
            from plyer import notification
            notification.notify(
                title="GestureDesk",
                message=text,
                app_name="GestureDesk",
                timeout=1
            )
        except Exception:
            pass
    threading.Thread(target=_show, daemon=True).start()

def take_screenshot():
    """Открывает инструмент выделения Windows."""
    # Сворачиваем окно камеры - иначе фокус на камере и Win+Shift+S не работает
    pyautogui.hotkey('win', 'down')  # свернуть текущее окно
    time.sleep(0.5)
    pyautogui.hotkey('win', 'shift', 's')
    print("📸 Инструмент скриншота открыт")

def show_desktop():
    """Показывает рабочий стол — сворачивает все окна."""
    # win+m сворачивает все окна надёжнее чем win+d
    pyautogui.hotkey('win', 'm')
    time.sleep(0.3)

def change_brightness(value, absolute=False):
    """Меняет яркость экрана. absolute=True — установить точное значение."""
    try:
        import screen_brightness_control as sbc
        if absolute:
            sbc.set_brightness(value)
        else:
            current = sbc.get_brightness()[0]
            new = max(10, min(100, current + value))
            sbc.set_brightness(new)
        print(f"☀️ Яркость изменена")
    except Exception as e:
        print(f"❌ Ошибка: pip install screen-brightness-control")

VOICE_COMMANDS = {
    # Приложения
    "ватсап":           (lambda: open_app("start whatsapp:"),           "📱 WhatsApp"),
    "вотсап":           (lambda: open_app("start whatsapp:"),           "📱 WhatsApp"),
    "whatsapp":         (lambda: open_app("start whatsapp:"),           "📱 WhatsApp"),
    "телеграм":         (lambda: open_app("start tg:"),                 "✈️ Telegram"),
    "telegram":         (lambda: open_app("start tg:"),                 "✈️ Telegram"),
    "инстаграм":        (lambda: open_url("https://instagram.com"),     "📸 Instagram"),
    "instagram":        (lambda: open_url("https://instagram.com"),     "📸 Instagram"),

    # Браузер
    "открой браузер":   (lambda: open_app("start chrome"),              "🌐 Браузер"),
    "открой ютуб":      (lambda: open_url("https://youtube.com"),       "📺 YouTube"),
    "youtube":          (lambda: open_url("https://youtube.com"),       "📺 YouTube"),
    "открой гугл":      (lambda: open_url("https://google.com"),        "🔍 Google"),
    "google":           (lambda: open_url("https://google.com"),        "🔍 Google"),
    "новая вкладка":    (lambda: pyautogui.hotkey('ctrl', 't'),         "➕ Новая вкладка"),
    "закрой вкладку":   (lambda: pyautogui.hotkey('ctrl', 'w'),         "❌ Закрыть вкладку"),
    "закрой":           (lambda: pyautogui.hotkey('alt', 'f4'),         "❌ Закрыть"),

    # Музыка
    "пауза":            (lambda: pyautogui.press('space'),               "⏸ Пауза"),
    "играй":            (lambda: pyautogui.press('space'),               "▶️ Играть"),
    "следующий":        (lambda: pyautogui.hotkey('nexttrack'),          "⏭ Следующий"),
    "предыдущий":       (lambda: pyautogui.hotkey('prevtrack'),          "⏮ Предыдущий"),
    "громче":           (lambda: pyautogui.press('volumeup'),            "🔊 Громче"),
    "тише":             (lambda: pyautogui.press('volumedown'),          "🔉 Тише"),
    "выключи звук":     (lambda: pyautogui.press('volumemute'),          "🔇 Без звука"),
    "включи звук":      (lambda: pyautogui.press('volumemute'),          "🔊 Включить звук"),
    "без звука":        (lambda: pyautogui.press('volumemute'),          "🔇 Без звука"),

    # Система
    "рабочий стол":     (lambda: pyautogui.hotkey('win', 'd'),           "🖥 Рабочий стол"),
    "скриншот":         (lambda: take_screenshot(),                      "📸 Скриншот"),
    "блокнот":          (lambda: open_app("notepad"),                    "📝 Блокнот"),
    "калькулятор":      (lambda: open_app("calc"),                       "🔢 Калькулятор"),
    "проводник":        (lambda: open_app("explorer"),                   "📁 Проводник"),
    "копировать":       (lambda: pyautogui.hotkey('ctrl', 'c'),          "📋 Копировать"),
    "вставить":         (lambda: pyautogui.hotkey('ctrl', 'v'),          "📋 Вставить"),
    "сохранить":        (lambda: pyautogui.hotkey('ctrl', 's'),          "💾 Сохранить"),
    "отменить":         (lambda: pyautogui.hotkey('ctrl', 'z'),          "↩️ Отменить"),
}

# ══════════════════════════════════════════
#  УМНАЯ СИСТЕМА СИНОНИМОВ
#  Формат: ([синонимы], действие, метка)
#  Работает через contains — понимает фразы!
# ══════════════════════════════════════════

SMART_COMMANDS = [
    # ── Приложения ──
    (["ватсап", "вотсап", "whatsapp", "вацап"],
        lambda: open_app("start whatsapp:"),           "📱 WhatsApp"),

    (["телеграм", "telegram"],
        lambda: open_app("start tg:"),                 "✈️ Telegram"),

    (["инстаграм", "instagram"],
        lambda: open_url("https://instagram.com"),     "📸 Instagram"),

    (["ютуб", "youtube"],
        lambda: open_url("https://youtube.com"),       "📺 YouTube"),

    (["гугл", "google"],
        lambda: open_url("https://google.com"),        "🔍 Google"),

    (["браузер", "хром", "chrome"],
        lambda: open_app("start chrome"),              "🌐 Браузер"),

    # ── Вкладки ──
    (["новая вкладка", "открой вкладку", "новую вкладку"],
        lambda: pyautogui.hotkey('ctrl', 't'),         "➕ Новая вкладка"),

    (["закрой вкладку", "закрыть вкладку"],
        lambda: pyautogui.hotkey('ctrl', 'w'),         "❌ Закрыть вкладку"),

    (["закрой окно", "закрыть окно", "выйти"],
        lambda: pyautogui.hotkey('alt', 'f4'),         "❌ Закрыть окно"),

    # ── Музыка ──
    (["пауза", "стоп", "остановить", "останови"],
        lambda: pyautogui.press('space'),              "⏸ Пауза"),

    (["играй", "продолжи", "включи музыку"],
        lambda: pyautogui.press('space'),              "▶️ Играть"),

    (["следующий", "следующая", "дальше"],
        lambda: pyautogui.hotkey('nexttrack'),         "⏭ Следующий"),

    (["предыдущий", "предыдущая"],
        lambda: pyautogui.hotkey('prevtrack'),         "⏮ Предыдущий"),

    (["громче", "прибавь звук", "увеличь звук"],
        lambda: pyautogui.press('volumeup'),           "🔊 Громче"),

    (["тише", "убавь звук", "уменьши звук"],
        lambda: pyautogui.press('volumedown'),         "🔉 Тише"),

    (["выключи звук", "включи звук", "без звука", "замолчи"],
        lambda: pyautogui.press('volumemute'),         "🔇 Звук вкл/выкл"),

    # ── Система ──
    (["рабочий стол", "сверни всё", "сверни все"],
        lambda: show_desktop(),                        "🖥 Рабочий стол"),

    (["скриншот", "снимок экрана", "сфотографируй"],
        lambda: take_screenshot(),                     "📸 Скриншот"),

    (["блокнот", "notepad"],
        lambda: open_app("notepad"),                   "📝 Блокнот"),

    (["калькулятор", "посчитай"],
        lambda: open_app("calc"),                      "🔢 Калькулятор"),

    (["проводник", "мои файлы", "папки"],
        lambda: open_app("explorer"),                  "📁 Проводник"),

    (["копировать", "скопируй"],
        lambda: pyautogui.hotkey('ctrl', 'c'),         "📋 Копировать"),

    (["вставить", "вставь"],
        lambda: pyautogui.hotkey('ctrl', 'v'),         "📋 Вставить"),

    (["сохранить", "сохрани"],
        lambda: pyautogui.hotkey('ctrl', 's'),         "💾 Сохранить"),

    (["выделить всё", "выделение", "выдели всё", "выдели", "выделить"],
        lambda: pyautogui.hotkey('ctrl', 'a'),         "🔵 Выделить всё"),

    # ── Яркость ──
    (["ярче", "увеличь яркость", "яркость больше"],
        lambda: change_brightness(+20),                "☀️ Ярче"),

    (["темнее", "уменьши яркость", "яркость меньше"],
        lambda: change_brightness(-20),                "🌙 Темнее"),

    (["максимальная яркость", "яркость максимум"],
        lambda: change_brightness(100, absolute=True), "☀️ Макс. яркость"),

    (["минимальная яркость", "яркость минимум"],
        lambda: change_brightness(10, absolute=True),  "🌙 Мин. яркость"),

    # ── Выход и Enter ──
    (["выйди", "выйти", "выйди отсюда", "закрой это", "escape", "эскейп"],
        lambda: pyautogui.press('escape'),             "⎋ Выход/Escape"),

    (["enter", "энтер", "подтверди", "ввод", "нажми", "клик", "нажать"],
        lambda: pyautogui.click(),                     "🖱 Клик"),

    (["закрой", "закрыть", "закрой окно", "закрыть окно"],
        lambda: pyautogui.hotkey('alt', 'f4'),         "❌ Закрыть"),

    (["отмена", "отменить", "отмени", "назад"],
        lambda: pyautogui.hotkey('ctrl', 'z'),         "↩️ Отмена"),

    # ── Время и дата ──
    (["который час", "сколько времени", "время"],
        lambda: say_time(),                            "🕐 Время"),

    (["какой день", "какое число", "дата", "какой сегодня"],
        lambda: say_date(),                            "📅 Дата"),

    # ── Переключение окон ──
    (["следующее окно", "переключи окно", "другое окно"],
        lambda: pyautogui.hotkey('alt', 'tab'),        "🔄 След. окно"),

    (["диспетчер", "процессы"],
        lambda: open_app("taskmgr"),                   "⚙️ Диспетчер задач"),

    (["vs code", "код", "редактор"],
        lambda: open_app("code"),                      "💻 VS Code"),
]


def say_time():
    """Показывает текущее время в логе."""
    now = datetime.now().strftime("%H:%M")
    log("🕐", f"Сейчас {now}", is_gesture=False)

def say_date():
    """Показывает текущую дату в логе."""
    months = ["января","февраля","марта","апреля","мая","июня",
              "июля","августа","сентября","октября","ноября","декабря"]
    now = datetime.now()
    log("📅", f"{now.day} {months[now.month-1]} {now.year}", is_gesture=False)


def find_smart_command(text):
    """Ищет команду через contains — понимает любые фразы с нужным словом."""
    for synonyms, action, label in SMART_COMMANDS:
        for word in synonyms:
            if word in text:
                return action, label
    return None, None


# ══════════════════════════════════════════
#  ГОЛОСОВОЙ МОДУЛЬ (в отдельном потоке)
# ══════════════════════════════════════════

recognizer = sr.Recognizer()
recognizer.energy_threshold    = 3000
recognizer.dynamic_energy_threshold = True

def handle_smart_voice(text):
    """Умные голосовые команды с переменным текстом."""

    # ── НАПЕЧАТАТЬ ТЕКСТ ──────────────────────────
    for prefix in ["напечатай ", "напиши ", "введи текст ", "печатай "]:
        if prefix in text:
            typed = text.split(prefix, 1)[1].strip()
            if typed:
                time.sleep(0.3)
                import pyperclip
                pyperclip.copy(typed)
                pyautogui.hotkey('ctrl', 'v')
                return f"⌨️ Напечатано: '{typed}'"

    # ── РЕЖИМ ВРАЧА ───────────────────────────────
    if any(w in text for w in ["режим врача", "медицинский режим", "включи режим врача"]):
        toggle_doctor_mode()
        return "🏥 Режим врача включён!"

    if any(w in text for w in ["обычный режим", "выключи режим врача", "стандартный режим"]):
        toggle_doctor_mode()
        return "💻 Обычный режим включён!"

    # Поиск в Google
    for prefix in ["найди в гугле ", "загугли ", "поищи в гугле ", "гугл ", "search google "]:
        if prefix in text:
            query = text.split(prefix, 1)[1].strip()
            if query:
                open_url(f"https://www.google.com/search?q={urllib.parse.quote(query)}")
                return f"🔍 Google: '{query}'"

    # Поиск на YouTube
    for prefix in ["найди на ютубе ", "поищи на ютубе ", "ютуб ", "search youtube "]:
        if prefix in text:
            query = text.split(prefix, 1)[1].strip()
            if query:
                open_url(f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}")
                return f"📺 YouTube: '{query}'"

    # Звонок в WhatsApp
    if ("позвони" in text or "позвонить" in text) and ("ватсап" in text or "whatsapp" in text):
        name = text
        for word in ["позвони", "позвонить", "в ватсапе", "ватсап", "whatsapp"]:
            name = name.replace(word, "")
        name = name.strip()
        open_app("start whatsapp:")
        time.sleep(3)
        if name:
            pyautogui.hotkey('ctrl', 'f')
            time.sleep(0.5)
            pyautogui.typewrite(name, interval=0.05)
            return f"📱 WhatsApp → '{name}'"
        return "📱 WhatsApp"

    # Написать в Telegram
    if ("напиши" in text or "написать" in text) and "телеграм" in text:
        name = text
        for word in ["напиши", "написать", "в телеграме", "телеграм"]:
            name = name.replace(word, "")
        name = name.strip()
        open_app("start tg:")
        time.sleep(3)
        if name:
            pyautogui.hotkey('ctrl', 'f')
            time.sleep(0.5)
            pyautogui.typewrite(name, interval=0.05)
            return f"✈️ Telegram → '{name}'"
        return "✈️ Telegram"

    # ── ИИ-команда отключена (нет API ключа) ──
    return None


def voice_thread():
    """Голосовой поток — работает параллельно с камерой."""
    with sr.Microphone() as source:
        recognizer.adjust_for_ambient_noise(source, duration=2)
        log("🎤", "Голос готов!")

        while True:
            try:
                audio = recognizer.listen(source, timeout=5, phrase_time_limit=6)
                text  = recognizer.recognize_google(audio, language=LANGUAGE).lower()

                # Умные команды (поиск, WhatsApp, Telegram, режим врача)
                result = handle_smart_voice(text)
                if result:
                    log("🎤", result, is_gesture=False)
                    continue

                # Режим врача — только безопасные команды
                if DOCTOR_MODE:
                    for synonyms, action, label in DOCTOR_COMMANDS:
                        for word in synonyms:
                            if word in text:
                                log("🏥", label, is_gesture=False)
                                action()
                                break
                    continue

                # Обычный режим — система синонимов
                action, label = find_smart_command(text)
                if action:
                    log("🎤", label, is_gesture=False)
                    action()
                else:
                    log("🎤", f"'{text}' — не понял", is_gesture=False)

            except sr.WaitTimeoutError:
                pass
            except sr.UnknownValueError:
                pass
            except sr.RequestError:
                log("🎤", "Нет интернета!")
                time.sleep(3)
            except Exception:
                pass


# ══════════════════════════════════════════
#  ЖЕСТОВЫЙ МОДУЛЬ
# ══════════════════════════════════════════

mp_hands = mp.solutions.hands
mp_draw  = mp.solutions.drawing_utils
hands    = mp_hands.Hands(max_num_hands=1, min_detection_confidence=0.75)

last_gesture_time = 0

def count_fingers(hand_landmarks):
    tips  = [8, 12, 16, 20]
    bases = [6, 10, 14, 18]
    lm    = hand_landmarks.landmark
    count = sum(1 for t, b in zip(tips, bases) if lm[t].y < lm[b].y)
    if lm[4].x < lm[3].x:
        count += 1
    return count

def handle_gesture(fingers):
    global last_gesture_time, last_screenshot_time
    now = time.time()
    if now - last_gesture_time < GESTURE_COOLDOWN:
        return None

    # ── РЕЖИМ ВРАЧА ──
    if DOCTOR_MODE:
        if fingers in DOCTOR_GESTURES:
            fn, label = DOCTOR_GESTURES[fingers]
            fn()
            last_gesture_time = now
            state["fingers"] = fingers
            log("🏥", label, is_gesture=True)
            return label
        return None

    # ── ОБЫЧНЫЙ РЕЖИМ ──
    if fingers == 5:
        if now - last_screenshot_time < SCREENSHOT_COOLDOWN:
            return None
        last_screenshot_time = now
        last_gesture_time = now
        state["fingers"] = fingers
        log("👋", "📸 Скриншот", is_gesture=True)
        threading.Thread(target=take_screenshot, daemon=True).start()
        return "📸 Скриншот"

    action_map = {
        0: (lambda: pyautogui.press('space'),           "⏸ Пауза/Плей"),
        1: (lambda: pyautogui.press('volumedown'),      "🔉 Тише"),
        2: (lambda: pyautogui.press('volumeup'),        "🔊 Громче"),
        3: (lambda: pyautogui.hotkey('nexttrack'),      "⏭ Следующий трек"),
        4: (lambda: show_desktop(),                     "🖥 Рабочий стол"),
    }

    if fingers in action_map:
        fn, label = action_map[fingers]
        fn()
        last_gesture_time = now
        state["fingers"] = fingers
        log("👋", label, is_gesture=True)
        return label
    return None


# ══════════════════════════════════════════
#  ОТРИСОВКА ИНТЕРФЕЙСА НА КАМЕРЕ
# ══════════════════════════════════════════

def draw_ui(frame, fingers):
    h, w, _ = frame.shape

    # Тёмная полоса сверху
    cv2.rectangle(frame, (0, 0), (w, 100), (20, 20, 20), -1)

    # Индикатор режима врача
    if DOCTOR_MODE:
        cv2.rectangle(frame, (0, 0), (w, 100), (0, 60, 30), -1)
        cv2.putText(frame, "🏥 РЕЖИМ ВРАЧА", (10, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 120), 2)
    else:
        cv2.putText(frame, "GestureDesk", (10, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.85, (100, 200, 255), 2)

    # Пальцы
    finger_txt = f"Пальцев: {fingers}" if fingers >= 0 else "Рука не найдена"
    cv2.putText(frame, finger_txt, (10, 60),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (100, 255, 100), 2)

    # Последнее действие
    cv2.putText(frame, f"{action_source}  {last_action}", (10, 90),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 210, 50), 2)

    # Лог внизу
    cv2.rectangle(frame, (0, h - 30 * 5 - 10), (w, h), (20, 20, 20), -1)
    with log_lock:
        for i, line in enumerate(reversed(log_lines)):
            y = h - 10 - i * 28
            color = (180, 180, 255) if "👋" in line else (255, 180, 180)
            cv2.putText(frame, line[-60:], (10, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.52, color, 1)

    # Подсказка
    cv2.putText(frame, "Q - выйти", (w - 120, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (150, 150, 150), 1)

    return frame


# ══════════════════════════════════════════
#  ЗАПУСК
# ══════════════════════════════════════════

def main():
    print("=" * 45)
    print("   GestureDesk — Жесты + Голос")
    print("=" * 45)
    print("Жесты: ✊=пауза  ☝️=тише  ✌️=громче  🤟=след  🖐=скриншот")
    print("Голос: 'открой ютуб', 'найди в гугле ...', 'телеграм'...")
    print("─" * 45)

    # Запускаем веб-сервер
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("🌐 Веб-панель: http://localhost:5000")
    time.sleep(1)
    subprocess.Popen("start http://localhost:5000", shell=True)

    # Запускаем голосовой поток
    t = threading.Thread(target=voice_thread, daemon=True)
    t.start()
    log("🎤", "Запускаю голос...")

    # Запускаем камеру
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("❌ Камера не найдена!")
        return

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        frame  = cv2.flip(frame, 1)
        rgb    = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = hands.process(rgb)

        fingers = -1
        if result.multi_hand_landmarks:
            for hand_lm in result.multi_hand_landmarks:
                mp_draw.draw_landmarks(frame, hand_lm, mp_hands.HAND_CONNECTIONS)
                fingers = count_fingers(hand_lm)
                handle_gesture(fingers)

        frame = draw_ui(frame, fingers)
        cv2.imshow("GestureDesk", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
    print("👋 GestureDesk остановлен.")


if __name__ == "__main__":
    main()

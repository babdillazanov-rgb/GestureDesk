"""
GestureDesk — 🏥 РЕЖИМ ВРАЧА
================================
Отдельная программа для медицинской среды.
Только безопасные команды: листание снимков, зум, пауза.

Запуск:
    cd doctor_mode
    python doctor.py

Жесты:
    ✊ 0 пальцев → Пауза
    ☝️ 1 палец   → Предыдущий снимок ←
    ✌️ 2 пальца  → Следующий снимок →
    🤟 3 пальца  → Увеличить 🔍
    🖐  4 пальца → Уменьшить 🔍
    🖐  5 пальцев→ Полный экран

Голос:
    "следующий"   → следующий снимок
    "предыдущий"  → предыдущий снимок
    "увеличить"   → зум +
    "уменьшить"   → зум -
    "пауза"       → пауза
    "полный экран"→ F11
"""

import cv2
import mediapipe as mp
import pyautogui
import speech_recognition as sr
import threading
import time
from datetime import datetime

# ══════════════════════════════════════════
#  НАСТРОЙКИ
# ══════════════════════════════════════════

LANGUAGE         = "ru-RU"
GESTURE_COOLDOWN = 1.0   # Секунд между жестами

pyautogui.FAILSAFE = True

# ══════════════════════════════════════════
#  ЛОГ
# ══════════════════════════════════════════

log_lines = []
last_action = ""

def log(source, message):
    global last_action
    last_action = message
    now = datetime.now().strftime("%H:%M:%S")
    entry = f"{source} {message}"
    log_lines.append(entry)
    if len(log_lines) > 6:
        log_lines.pop(0)
    print(f"[{now}] {entry}")

# ══════════════════════════════════════════
#  КОМАНДЫ (только безопасные!)
# ══════════════════════════════════════════

DOCTOR_COMMANDS = [
    (["следующий снимок", "следующий", "дальше", "вперёд"],
        lambda: pyautogui.press('right'),              "📋 Следующий снимок"),

    (["предыдущий снимок", "предыдущий", "назад"],
        lambda: pyautogui.press('left'),               "📋 Предыдущий снимок"),

    (["увеличить", "увеличь", "приблизить"],
        lambda: pyautogui.hotkey('ctrl', '+'),         "🔍 Увеличить"),

    (["уменьшить", "уменьши", "отдалить"],
        lambda: pyautogui.hotkey('ctrl', '-'),         "🔍 Уменьшить"),

    (["исходный размер", "сбросить", "нормальный"],
        lambda: pyautogui.hotkey('ctrl', '0'),         "🔍 Исходный размер"),

    (["пауза", "стоп", "остановить"],
        lambda: pyautogui.press('space'),              "⏸ Пауза"),

    (["полный экран", "на весь экран"],
        lambda: pyautogui.press('f11'),                "🖥 Полный экран"),

    (["вниз", "прокрутить вниз", "листай вниз"],
        lambda: pyautogui.press('pagedown'),           "⬇️ Вниз"),

    (["вверх", "прокрутить вверх", "листай вверх"],
        lambda: pyautogui.press('pageup'),             "⬆️ Вверх"),

    (["выход", "закрыть режим", "стоп режим"],
        lambda: exit_program(),                        "🚪 Выход"),
]

# Жесты
DOCTOR_GESTURES = {
    0: (lambda: pyautogui.press('space'),          "⏸ Пауза"),
    1: (lambda: pyautogui.press('left'),           "📋 Предыдущий"),
    2: (lambda: pyautogui.press('right'),          "📋 Следующий"),
    3: (lambda: pyautogui.hotkey('ctrl', '+'),     "🔍 Увеличить"),
    4: (lambda: pyautogui.hotkey('ctrl', '-'),     "🔍 Уменьшить"),
    5: (lambda: pyautogui.press('f11'),            "🖥 Полный экран"),
}

# Флаг для остановки программы
running = True

def exit_program():
    global running
    running = False
    log("🚪", "Выход из режима врача")

# ══════════════════════════════════════════
#  ГОЛОСОВОЙ МОДУЛЬ
# ══════════════════════════════════════════

recognizer = sr.Recognizer()
recognizer.energy_threshold = 3000
recognizer.dynamic_energy_threshold = True

def voice_thread():
    with sr.Microphone() as source:
        recognizer.adjust_for_ambient_noise(source, duration=2)
        log("🎤", "Голос готов!")

        while running:
            try:
                audio = recognizer.listen(source, timeout=5, phrase_time_limit=5)
                text  = recognizer.recognize_google(audio, language=LANGUAGE).lower()

                matched = False
                for synonyms, action, label in DOCTOR_COMMANDS:
                    for word in synonyms:
                        if word in text:
                            log("🎤", label)
                            action()
                            matched = True
                            break
                    if matched:
                        break

                if not matched:
                    log("🎤", f"'{text}' — не в режиме врача")

            except sr.WaitTimeoutError:
                pass
            except sr.UnknownValueError:
                pass
            except sr.RequestError:
                log("🎤", "Нет интернета!")
                time.sleep(2)
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
    global last_gesture_time
    now = time.time()
    if now - last_gesture_time < GESTURE_COOLDOWN:
        return
    if fingers in DOCTOR_GESTURES:
        fn, label = DOCTOR_GESTURES[fingers]
        fn()
        last_gesture_time = now
        log("👋", label)

# ══════════════════════════════════════════
#  ИНТЕРФЕЙС НА КАМЕРЕ
# ══════════════════════════════════════════

def draw_ui(frame, fingers):
    h, w, _ = frame.shape

    # Зелёная полоса сверху — признак режима врача
    cv2.rectangle(frame, (0, 0), (w, 110), (0, 50, 25), -1)

    # Заголовок
    cv2.putText(frame, "DOCTOR MODE", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 120), 2)

    # Крест (символ медицины)
    cv2.putText(frame, "+", (w - 40, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 120), 3)

    # Пальцев
    finger_txt = f"Пальцев: {fingers}" if fingers >= 0 else "Рука не найдена"
    cv2.putText(frame, finger_txt, (10, 65),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (180, 255, 180), 2)

    # Последнее действие
    cv2.putText(frame, last_action[:50], (10, 98),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 220, 50), 2)

    # Лог внизу
    cv2.rectangle(frame, (0, h - 160), (w, h), (0, 30, 15), -1)
    for i, line in enumerate(reversed(log_lines[-5:])):
        y = h - 10 - i * 28
        cv2.putText(frame, line[-55:], (10, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 255, 150), 1)

    # Подсказка жестов справа
    gestures_hint = [
        "✊=пауза", "1=пред", "2=след",
        "3=zoom+", "4=zoom-", "5=fullscreen"
    ]
    for i, hint in enumerate(gestures_hint):
        cv2.putText(frame, hint, (w - 130, 30 + i * 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 255, 150), 1)

    # Выход
    cv2.putText(frame, "Q - выйти", (10, h - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 100, 100), 1)

    return frame

# ══════════════════════════════════════════
#  ЗАПУСК
# ══════════════════════════════════════════

def main():
    global running

    print("=" * 45)
    print("   🏥 GestureDesk — РЕЖИМ ВРАЧА")
    print("=" * 45)
    print("Жесты: ✊=пауза  ☝️=пред  ✌️=след  🤟=zoom+  🖐=zoom-")
    print("Голос: 'следующий', 'увеличить', 'пауза'...")
    print("Q — выйти")
    print("─" * 45)

    # Голосовой поток
    t = threading.Thread(target=voice_thread, daemon=True)
    t.start()

    # Камера
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("❌ Камера не найдена!")
        return

    while cap.isOpened() and running:
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
        cv2.imshow("GestureDesk — Doctor Mode", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
    print("🏥 Режим врача остановлен.")


if __name__ == "__main__":
    main()

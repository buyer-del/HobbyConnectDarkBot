# ============================================
#  🔊 Аудіо → Google Speech-to-Text (uk-UA)
#  🖼️ Зображення → Google Vision API (OCR)
# ============================================

import os
import io
import subprocess
import tempfile
from typing import Optional

from google.cloud import speech_v1 as speech
from google.cloud import vision

# -----------------------------
# Налаштування Google Credentials
# -----------------------------
def _setup_google_credentials() -> None:
    """
    Налаштовує GOOGLE_APPLICATION_CREDENTIALS на основі
    змінної середовища GOOGLE_CREDENTIALS_JSON (як у твоєму коді).
    """
    google_creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if not google_creds_json:
        raise ValueError("❌ GOOGLE_CREDENTIALS_JSON не знайдено у змінних середовища!")

    creds_path = "/tmp/google_credentials.json"
    with open(creds_path, "w", encoding="utf-8") as f:
        f.write(google_creds_json)

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path

_setup_google_credentials()

# Мова розпізнавання (за потреби можна змінити через SPEECH_LANGUAGE)
SPEECH_LANGUAGE = os.getenv("SPEECH_LANGUAGE", "uk-UA")


# -----------------------------
# Допоміжне: конвертація → WAV
# -----------------------------
def _convert_to_wav_16k_mono(input_path: str) -> str:
    """
    Конвертує будь-яке аудіо/відео в WAV PCM 16-bit, mono, 16000 Hz.
    Вимагає наявності ffmpeg у середовищі (на Render він зазвичай є).
    Повертає шлях до тимчасового .wav файлу.
    """
    fd, out_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)

    # -vn: відкинути відео (на випадок .mp4/.webm)
    # -ac 1: моно
    # -ar 16000: 16 кГц
    # -sample_fmt s16: 16-бітний PCM
    cmd = [
        "ffmpeg",
        "-hide_banner", "-loglevel", "error",
        "-y",
        "-i", input_path,
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-sample_fmt", "s16",
        out_path,
    ]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        # Якщо ffmpeg не зміг сконвертувати
        try:
            os.remove(out_path)
        except Exception:
            pass
        raise RuntimeError(f"ffmpeg: помилка конвертації ({e})")

    return out_path


# -----------------------------
# Google Speech-to-Text
# -----------------------------
def transcribe_audio(input_path: str) -> Optional[str]:
    """
    Розпізнає українську мову з аудіо через Google Speech-to-Text.
    1) Завжди конвертує у WAV PCM 16k/16-bit/mono
    2) Виконує розпізнавання
    3) Повертає текст або None (якщо не розпізнано/помилка)

    ВАЖЛИВО: Ми повертаємо None на невдачу, бо main.py показує власне повідомлення
    про помилку — це зберігає поточну поведінку бота.
    """
    wav_path = None
    try:
        # Конвертація у WAV
        wav_path = _convert_to_wav_16k_mono(input_path)

        # Читаємо бінарний вміст
        with open(wav_path, "rb") as f:
            content = f.read()

        audio = speech.RecognitionAudio(content=content)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=16000,
            language_code=SPEECH_LANGUAGE,
            enable_automatic_punctuation=True,
            # "latest_long" добре працює з фразами; за потреби можна "default"
            model="latest_long",
        )

        client = speech.SpeechClient()
        response = client.recognize(config=config, audio=audio)

        # Якщо немає результатів
        if not response.results:
            return None

        parts = []
        for result in response.results:
            if result.alternatives:
                parts.append(result.alternatives[0].transcript)

        text = " ".join(t.strip() for t in parts if t and t.strip())
        return text if text else None

    except Exception as e:
        # Логіку повідомлення користувачу робить main.py,
        # тому тут повертаємо None, щоб main показав свою фразу.
        return None

    finally:
        # Прибираємо тимчасовий .wav файл
        if wav_path and os.path.exists(wav_path):
            try:
                os.remove(wav_path)
            except Exception:
                pass


# -----------------------------
# Google Vision OCR
# -----------------------------
def extract_text_from_image(image_path: str) -> Optional[str]:
    """
    Розпізнає текст із зображення через Google Vision API.
    Повертає рядок або None.
    """
    try:
        client = vision.ImageAnnotatorClient()

        with open(image_path, "rb") as image_file:
            content = image_file.read()

        image = vision.Image(content=content)
        response = client.text_detection(image=image)

        if response.error.message:
            # Прокидуємо як виняток, щоб верхній рівень показав повідомлення про помилку
            raise RuntimeError(f"Vision API error: {response.error.message}")

        if not response.text_annotations:
            return None

        full_text = (response.text_annotations[0].description or "").strip()
        return full_text or None

    except Exception:
        return None

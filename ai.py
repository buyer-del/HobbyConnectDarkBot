# ============================================
#  🔊 Аудіо → Google Speech-to-Text (українська)
#  🖼️ Зображення → Google Vision API (OCR)
# ============================================

import os
import json
from google.cloud import speech
from google.cloud import vision
from pydub import AudioSegment
import io

# ---- Google Speech-to-Text з Replit Secrets ----
def _setup_google_credentials():
    """Налаштовує Google Cloud credentials з Replit Secrets"""
    google_creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if not google_creds_json:
        raise ValueError("❌ GOOGLE_CREDENTIALS_JSON не знайдено у Replit Secrets!")
    
    # Зберігаємо credentials у тимчасовий файл
    creds_path = "/tmp/google_credentials.json"
    with open(creds_path, "w") as f:
        f.write(google_creds_json)
    
    # Встановлюємо змінну середовища для Google SDK
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path

# Викликаємо один раз при імпорті модуля
_setup_google_credentials()


def transcribe_audio(file_path: str) -> str:
    """
    Розпізнає українську мову з аудіо через Google Speech-to-Text.
    Підтримує різні формати (.ogg, .mp3, .m4a, .wav тощо).
    """
    try:
        # 1. Конвертуємо будь-яке аудіо у WAV 16kHz mono
        wav_path = file_path + ".wav"
        sound = AudioSegment.from_file(file_path)
        sound = sound.set_frame_rate(16000).set_channels(1)
        sound.export(wav_path, format="wav")

        # 2. Завантажуємо аудіо у пам'ять
        with io.open(wav_path, "rb") as audio_file:
            content = audio_file.read()

        # 3. Налаштування клієнта Speech API
        client = speech.SpeechClient()
        audio = speech.RecognitionAudio(content=content)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=16000,
            language_code="uk-UA",
            enable_automatic_punctuation=True,
        )

        # 4. Відправляємо запит до Google Speech-to-Text
        response = client.recognize(config=config, audio=audio)

        # 5. Очищаємо тимчасові файли
        if os.path.exists(wav_path):
            os.remove(wav_path)

        # 6. Отримуємо результат
        if not response.results:
            return "(мову не розпізнано)"

        text = " ".join([result.alternatives[0].transcript for result in response.results])
        return text.strip()

    except Exception as e:
        return f"Помилка транскрипції: {e}"


# --- Google Vision API (розпізнавання тексту з картинок) ---
from google.cloud import vision

def extract_text_from_image(image_path: str) -> str:
    """
    Розпізнає текст з зображення через Google Vision API.
    Підтримує українську мову та багато інших.
    """
    try:
        # Ініціалізуємо Vision API client
        client = vision.ImageAnnotatorClient()

        # Читаємо зображення
        with io.open(image_path, 'rb') as image_file:
            content = image_file.read()

        image = vision.Image(content=content)

        # Розпізнаємо текст
        response = client.text_detection(image=image)
        texts = response.text_annotations

        if texts:
            # Перший елемент містить весь текст
            return texts[0].description.strip()
        else:
            return "(текст не розпізнано)"

    except Exception as e:
        return f"Помилка OCR: {e}"

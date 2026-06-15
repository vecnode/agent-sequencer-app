import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1")
    WEB_PORT = int(os.getenv("WEB_PORT", 8000))

    TTS_DEFAULT_LANG = os.getenv("TTS_DEFAULT_LANG", "en")
    TTS_DEFAULT_VOICE = os.getenv("TTS_DEFAULT_VOICE", "F1")

    ENGINES_PRELOAD_ON_STARTUP = os.getenv("ENGINES_PRELOAD_ON_STARTUP", "true").lower() == "true"

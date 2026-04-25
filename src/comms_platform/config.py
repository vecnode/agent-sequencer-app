import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    TD_HOST = os.getenv("TD_HOST", "127.0.0.1")
    TD_PORT = int(os.getenv("TD_PORT", 7000))
    MODEL_NAME = os.getenv("MODEL_NAME", "feature-extraction")
    DEVICE = os.getenv("DEVICE", "cuda")
    THREAD_TIMEOUT_SECONDS = float(os.getenv("THREAD_TIMEOUT_SECONDS", 5.0))
    WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1")
    WEB_PORT = int(os.getenv("WEB_PORT", 8000))

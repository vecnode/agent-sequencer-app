import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    TD_HOST = os.getenv("TD_HOST", "127.0.0.1")
    TD_PORT = int(os.getenv("TD_PORT", 7000))
    OSC_INPUT_HOST = os.getenv("OSC_INPUT_HOST", "0.0.0.0")
    OSC_INPUT_PORT = int(os.getenv("OSC_INPUT_PORT", 7001))
    MODEL_NAME = os.getenv("MODEL_NAME", "feature-extraction")
    DEVICE = os.getenv("DEVICE", "cuda")
    THREAD_TIMEOUT_SECONDS = float(os.getenv("THREAD_TIMEOUT_SECONDS", 5.0))
    WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1")
    WEB_PORT = int(os.getenv("WEB_PORT", 8000))
    TD_WEB_HOST = os.getenv("TD_WEB_HOST", "127.0.0.1")
    TD_WEB_PORT = int(os.getenv("TD_WEB_PORT", 9980))
    OLLAMA_HOST = os.getenv("OLLAMA_HOST", "127.0.0.1")
    OLLAMA_PORT = int(os.getenv("OLLAMA_PORT", 11434))
    INTENT_ENGINE_ENABLED = os.getenv("INTENT_ENGINE_ENABLED", "true").lower() == "true"
    INTENT_MODEL_NAME = os.getenv(
        "INTENT_MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2"
    )
    INTENT_CONFIDENCE_THRESHOLD = float(os.getenv("INTENT_CONFIDENCE_THRESHOLD", 0.7))
    INTENT_UNCERTAIN_THRESHOLD = float(os.getenv("INTENT_UNCERTAIN_THRESHOLD", 0.45))

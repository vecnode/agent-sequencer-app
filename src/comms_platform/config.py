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
    
    PERCEPTION_ENGINE_ENABLED = (
        os.getenv("PERCEPTION_ENGINE_ENABLED", os.getenv("INTENT_ENGINE_ENABLED", "true")).lower() == "true"
    )
    PERCEPTION_MODEL_NAME = os.getenv(
        "PERCEPTION_MODEL_NAME",
        os.getenv("INTENT_MODEL_NAME", ""),
    )
    PERCEPTION_CONFIDENCE_THRESHOLD = float(
        os.getenv("PERCEPTION_CONFIDENCE_THRESHOLD", os.getenv("INTENT_CONFIDENCE_THRESHOLD", 0.7))
    )
    PERCEPTION_UNCERTAIN_THRESHOLD = float(
        os.getenv("PERCEPTION_UNCERTAIN_THRESHOLD", os.getenv("INTENT_UNCERTAIN_THRESHOLD", 0.45))
    )

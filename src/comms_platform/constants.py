import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_TOE_PATH = PROJECT_ROOT / "touchdesigner" / "example1.toe"

TD_WEB_DEFAULT_HOST = os.getenv("TD_WEB_HOST", "127.0.0.1")
TD_WEB_DEFAULT_PORT = int(os.getenv("TD_WEB_PORT", 9980))
OLLAMA_DEFAULT_HOST = os.getenv("OLLAMA_HOST", "127.0.0.1")
OLLAMA_DEFAULT_PORT = int(os.getenv("OLLAMA_PORT", 11434))
TTS_DEFAULT_LANG = os.getenv("TTS_DEFAULT_LANG", "en")
TTS_DEFAULT_VOICE = os.getenv("TTS_DEFAULT_VOICE", "F1")
TTS_PREWARM_ON_STARTUP = os.getenv("TTS_PREWARM_ON_STARTUP", "false").lower() == "true"
TTI_DEFAULT_GUIDANCE = float(
    os.getenv("TTI_DEFAULT_GUIDANCE", os.getenv("SDXL_DEFAULT_GUIDANCE", "7.0"))
)
TTI_DEFAULT_STEPS = int(os.getenv("TTI_DEFAULT_STEPS", os.getenv("SDXL_DEFAULT_STEPS", "20")))
TTS_TEST_PROMPT = "hello world"
TTI_TEST_PROMPT = "a beautiful sunny city with cars"
UNREAL_AUDIO_INTERVAL_SECONDS = float(os.getenv("UNREAL_AUDIO_INTERVAL_SECONDS", "10"))
UNREAL_AUDIO_PROMPT = os.getenv(
    "UNREAL_AUDIO_PROMPT",
    "Create a short atmospheric narration for a realtime interactive world.",
)
UNREAL_IMAGE_PROMPT = os.getenv(
    "UNREAL_IMAGE_PROMPT",
    "cinematic concept art, dynamic composition, volumetric lighting, ultra detailed",
)
CHAT_REPLY_MAX_CHARS = int(os.getenv("CHAT_REPLY_MAX_CHARS", "1800"))
CHAT_REPLY_MAX_TOKENS = int(os.getenv("CHAT_REPLY_MAX_TOKENS", "450"))

from dataclasses import dataclass
from typing import Any


@dataclass
class AppContext:
    config: Any | None = None
    tts_default_lang: str = "en"
    tts_default_voice: str = "F1"

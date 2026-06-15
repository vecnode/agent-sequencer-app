from dataclasses import dataclass
from typing import Any

from ..services.inference_service import InferenceService


@dataclass
class AppContext:
    config: Any | None = None
    inference_service: InferenceService | None = None
    tts_default_lang: str = "en"
    tts_default_voice: str = "F1"

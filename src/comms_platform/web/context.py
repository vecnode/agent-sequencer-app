import asyncio
from dataclasses import dataclass
from typing import Any


@dataclass
class AppContext:
    event_bus: Any
    thread_manager: Any
    signal_gateway: Any
    master_agent: Any
    config: Any | None = None

    ollama_url: str = ""
    td_web_url: str = ""
    tts_default_lang: str = "en"
    tts_default_voice: str = "F1"
    selected_model: str | None = None

    unreal_audio_task: asyncio.Task | None = None
    unreal_image_task: asyncio.Task | None = None

import os
from typing import Any

from pydantic import BaseModel, Field


class SignalPayload(BaseModel):
    address: str
    params: list[Any] = Field(default_factory=list)
    source: str = "external-app"
    protocol: str = "stream"
    direction: str = "inbound"
    target: str = "platform"


class TdWebPayload(BaseModel):
    payload: dict[str, Any] = Field(default_factory=lambda: {"test_key": "test_value"})
    timeout: float = Field(default=5.0, gt=0, le=30)


class AgentMessagePayload(BaseModel):
    text: str = Field(min_length=1)
    selected_model: str | None = None


class TtsPayload(BaseModel):
    text: str = Field(min_length=1)
    lang: str = Field(default=os.getenv("TTS_DEFAULT_LANG", "en"), min_length=2, max_length=8)
    voice_name: str = Field(default=os.getenv("TTS_DEFAULT_VOICE", "F1"), min_length=1, max_length=32)


class TtiGeneratePayload(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    guidance_scale: float = Field(
        default=float(os.getenv("TTI_DEFAULT_GUIDANCE", os.getenv("SDXL_DEFAULT_GUIDANCE", "7.0"))),
        ge=1.0,
        le=20.0,
    )
    num_inference_steps: int = Field(
        default=int(os.getenv("TTI_DEFAULT_STEPS", os.getenv("SDXL_DEFAULT_STEPS", "20"))),
        ge=5,
        le=75,
    )
    seed: int | None = Field(default=None, ge=0, le=4294967295)


class UnrealEventPayload(BaseModel):
    source: str = Field(default="unreal", min_length=1, max_length=64)
    event: str = Field(min_length=1, max_length=128)
    message: str = Field(default="", max_length=2048)
    timestamp_utc: str = Field(default="")
    session_id: str | None = Field(default=None, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SendToUnrealPayload(BaseModel):
    message: str = Field(default="Hello from platform", max_length=2048)
    unreal_host: str = Field(default="127.0.0.1", max_length=255)
    unreal_port: int = Field(default=30080, ge=1024, le=65535)

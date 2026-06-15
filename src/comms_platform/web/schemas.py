import os

from pydantic import BaseModel, Field


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


class Tt3dGeneratePayload(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    guidance_scale: float = Field(
        default=float(os.getenv("TT3D_DEFAULT_GUIDANCE", "7.5")),
        ge=1.0,
        le=20.0,
    )
    num_inference_steps: int = Field(
        default=int(os.getenv("TT3D_DEFAULT_STEPS", "30")),
        ge=5,
        le=75,
    )
    seed: int | None = Field(default=None, ge=0, le=4294967295)
    enable_texture: bool | None = None
    octree_resolution: int = Field(
        default=int(os.getenv("TT3D_DEFAULT_OCTREE_RESOLUTION", "256")),
        ge=128,
        le=512,
    )


class InferencePromptPayload(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)

"""Shared inference prompt state for TTS, TTI, and TT3D generation."""

from __future__ import annotations

import threading
from typing import Any

from ..constants import TTI_TEST_PROMPT, TTS_TEST_PROMPT, TT3D_TEST_PROMPT

_lock = threading.RLock()
_global_prompt: str = TTS_TEST_PROMPT


def get_global_inference_prompt() -> str:
    with _lock:
        return _global_prompt


def set_global_inference_prompt(prompt: str) -> str:
    global _global_prompt
    clean = str(prompt or "").strip()
    if not clean:
        raise ValueError("prompt_required")
    with _lock:
        _global_prompt = clean
        return _global_prompt


def get_inference_prompt_state() -> dict[str, Any]:
    with _lock:
        return {
            "prompt": _global_prompt,
            "engines": ["tts", "tti", "tt3d"],
            "defaults": {
                "tts": TTS_TEST_PROMPT,
                "tti": TTI_TEST_PROMPT,
                "tt3d": TT3D_TEST_PROMPT,
            },
        }

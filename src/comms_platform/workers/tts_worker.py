from __future__ import annotations

import base64
import os
from typing import Any

from ..constants import ENGINES_PRELOAD_ON_STARTUP, TTS_DEFAULT_LANG, TTS_DEFAULT_VOICE
from ..inference.tts import (
    check_tts_engine_status,
    get_tts_engine_loaded_state,
    set_tts_engine_loaded,
    synthesize_tts_audio_bytes,
)
from ._runner import run_worker_loop


def _handle(method: str, params: dict[str, Any]) -> dict[str, Any]:
    if method == "ping":
        return {"engine": "SuperTonic 3", "ready": True}
    if method == "engine_on":
        return set_tts_engine_loaded(True)
    if method == "engine_off":
        return set_tts_engine_loaded(False)
    if method == "status":
        voice = str(params.get("voice_name") or TTS_DEFAULT_VOICE)
        return check_tts_engine_status(voice)
    if method == "loaded_state":
        return get_tts_engine_loaded_state()
    if method == "synthesize":
        result = synthesize_tts_audio_bytes(
            str(params["text"]),
            str(params.get("lang") or TTS_DEFAULT_LANG),
            str(params.get("voice_name") or TTS_DEFAULT_VOICE),
        )
        if result.get("ok") and isinstance(result.get("audio_bytes"), (bytes, bytearray)):
            encoded = dict(result)
            encoded["audio_bytes"] = base64.b64encode(encoded["audio_bytes"]).decode("ascii")
            encoded["audio_encoding"] = "base64"
            return encoded
        return result
    raise ValueError(f"unknown_method:{method}")


def _preload() -> dict[str, Any]:
    if ENGINES_PRELOAD_ON_STARTUP:
        return set_tts_engine_loaded(True)
    return {"ok": True, "loaded": False}


def main() -> int:
    return run_worker_loop(engine_name="tts", handler=_handle, preload=_preload)


if __name__ == "__main__":
    raise SystemExit(main())

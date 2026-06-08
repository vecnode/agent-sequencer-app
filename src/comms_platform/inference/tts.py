import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from ..utils.logger import get_logger

logger = get_logger("inference.tts")

_tts_engine: Any | None = None
_tts_engine_lock = threading.Lock()


def _coerce_duration_seconds(value: Any) -> float:
    """Best-effort conversion for SDK duration outputs (float, numpy scalar, or arrays)."""
    try:
        return float(value)
    except Exception:
        pass

    item_fn = getattr(value, "item", None)
    if callable(item_fn):
        try:
            return float(item_fn())
        except Exception:
            pass

    tolist_fn = getattr(value, "tolist", None)
    if callable(tolist_fn):
        try:
            list_value = tolist_fn()
            if isinstance(list_value, list) and list_value:
                return float(list_value[0])
            return float(list_value)
        except Exception:
            pass

    if isinstance(value, (list, tuple)) and value:
        try:
            return float(value[0])
        except Exception:
            pass

    return 0.0


def get_tts_engine() -> Any:
    global _tts_engine
    with _tts_engine_lock:
        if _tts_engine is None:
            from supertonic import TTS

            _tts_engine = TTS(auto_download=True)
            logger.info("Supertonic TTS engine initialized.")
        return _tts_engine


def set_tts_engine_loaded(loaded: bool) -> dict:
    global _tts_engine
    with _tts_engine_lock:
        if loaded:
            if _tts_engine is None:
                from supertonic import TTS

                _tts_engine = TTS(auto_download=True)
                logger.info("Supertonic TTS engine initialized.")
            return {"ok": True, "engine": "SuperTonic 3", "loaded": True}

        if _tts_engine is not None:
            close_fn = getattr(_tts_engine, "close", None)
            if callable(close_fn):
                try:
                    close_fn()
                except Exception:
                    pass
        _tts_engine = None
        return {"ok": True, "engine": "SuperTonic 3", "loaded": False}


def get_tts_engine_loaded_state() -> dict:
    with _tts_engine_lock:
        return {
            "ok": True,
            "engine": "SuperTonic 3",
            "loaded": _tts_engine is not None,
        }


def synthesize_tts_audio_bytes(text: str, lang: str, voice_name: str) -> dict:
    try:
        tts = get_tts_engine()
        style = tts.get_voice_style(voice_name=voice_name)
        wav, duration = tts.synthesize(text, voice_style=style, lang=lang)

        fd, temp_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            tts.save_audio(wav, temp_path)
            audio_bytes = Path(temp_path).read_bytes()
        finally:
            try:
                os.remove(temp_path)
            except OSError:
                pass

        return {
            "ok": True,
            "audio_bytes": audio_bytes,
            "duration": _coerce_duration_seconds(duration),
            "voice_name": voice_name,
            "lang": lang,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
        }


def prewarm_tts_engine() -> None:
    try:
        get_tts_engine()
        logger.info("Supertonic TTS prewarm completed.")
    except Exception as exc:
        logger.warning("Supertonic TTS prewarm failed: %s", exc)


def check_tts_engine_status(voice_name: str) -> dict:
    try:
        state = get_tts_engine_loaded_state()
        return {
            "ok": True,
            "engine": state["engine"],
            "loaded": state["loaded"],
            "voice_name": voice_name,
        }
    except Exception as exc:
        return {
            "ok": False,
            "engine": "SuperTonic 3",
            "voice_name": voice_name,
            "error": str(exc),
        }

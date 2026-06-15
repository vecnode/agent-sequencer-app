"""Startup loading for TTS, TTI, and TT3D inference engines."""

from __future__ import annotations

from typing import Any

from ..utils.logger import get_logger
from .tti import set_tti_engine_loaded
from .tt3d import prepare_tt3d_runtime, set_tt3d_engine_loaded
from .tts import set_tts_engine_loaded

logger = get_logger("inference.startup")


def preload_inference_engines() -> dict[str, Any]:
    """Load TTS, TTI, and TT3D pipelines so they are ready before the first API request."""
    prepare_tt3d_runtime()

    results: dict[str, Any] = {"ok": True, "engines": {}}

    tts_result = set_tts_engine_loaded(True)
    results["engines"]["tts"] = tts_result
    if not tts_result.get("loaded"):
        results["ok"] = False
        logger.warning("TTS preload failed: %s", tts_result)
    else:
        logger.info("TTS engine preloaded.")

    tti_result = set_tti_engine_loaded(True)
    results["engines"]["tti"] = tti_result
    if not tti_result.get("loaded"):
        results["ok"] = False
        logger.warning("TTI preload failed: %s", tti_result)
    else:
        logger.info("TTI engine preloaded on %s.", tti_result.get("device"))

    tt3d_result = set_tt3d_engine_loaded(True)
    results["engines"]["tt3d"] = tt3d_result
    if not tt3d_result.get("loaded"):
        results["ok"] = False
        logger.warning("TT3D preload failed: %s", tt3d_result)
    else:
        logger.info("TT3D engine preloaded on %s.", tt3d_result.get("device"))

    if results["ok"]:
        logger.info("All inference engines preloaded and ready.")
    else:
        logger.warning("One or more inference engines failed to preload.")

    return results

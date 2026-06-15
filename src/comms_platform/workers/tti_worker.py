from __future__ import annotations

from typing import Any

from ..constants import ENGINES_PRELOAD_ON_STARTUP
from ..inference.tti import (
    generate_tti_image,
    get_tti_engine_loaded_state,
    set_tti_engine_loaded,
)
from ._runner import run_worker_loop


def _handle(method: str, params: dict[str, Any]) -> dict[str, Any]:
    if method == "ping":
        return {"engine": "SDXL Base 1", "ready": True}
    if method == "engine_on":
        return set_tti_engine_loaded(True)
    if method == "engine_off":
        return set_tti_engine_loaded(False)
    if method == "status":
        return get_tti_engine_loaded_state()
    if method == "loaded_state":
        return get_tti_engine_loaded_state()
    if method == "generate":
        return generate_tti_image(
            str(params["prompt"]),
            float(params.get("guidance_scale", 7.0)),
            int(params.get("num_inference_steps", 20)),
            params.get("seed"),
        )
    raise ValueError(f"unknown_method:{method}")


def _preload() -> dict[str, Any]:
    if ENGINES_PRELOAD_ON_STARTUP:
        return set_tti_engine_loaded(True)
    return {"ok": True, "loaded": False}


def main() -> int:
    return run_worker_loop(engine_name="tti", handler=_handle, preload=_preload)


if __name__ == "__main__":
    raise SystemExit(main())

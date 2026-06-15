from __future__ import annotations

from typing import Any

from ..constants import ENGINES_PRELOAD_ON_STARTUP
from ..inference.tt3d import (
    generate_tt3d_asset,
    get_tt3d_engine_loaded_state,
    prepare_tt3d_runtime,
    set_tt3d_engine_loaded,
)
from ._runner import run_worker_loop


def _handle(method: str, params: dict[str, Any]) -> dict[str, Any]:
    if method == "ping":
        return {"engine": "Hunyuan3D 2.1", "ready": True}
    if method == "engine_on":
        return set_tt3d_engine_loaded(True)
    if method == "engine_off":
        return set_tt3d_engine_loaded(False)
    if method == "status":
        return get_tt3d_engine_loaded_state()
    if method == "loaded_state":
        return get_tt3d_engine_loaded_state()
    if method == "generate":
        return generate_tt3d_asset(
            str(params["prompt"]),
            float(params.get("guidance_scale", 7.5)),
            int(params.get("num_inference_steps", 30)),
            params.get("seed"),
            reference_file=params.get("reference_file"),
            octree_resolution=int(params.get("octree_resolution", 256)),
        )
    raise ValueError(f"unknown_method:{method}")


def _preload() -> dict[str, Any]:
    prepare_tt3d_runtime()
    if ENGINES_PRELOAD_ON_STARTUP:
        return set_tt3d_engine_loaded(True)
    return {"ok": True, "loaded": False}


def main() -> int:
    return run_worker_loop(engine_name="tt3d", handler=_handle, preload=_preload)


if __name__ == "__main__":
    raise SystemExit(main())

import asyncio

from ..context import AppContext
from ...inference.tti import get_tti_engine_loaded_state
from ...inference.tt3d import get_tt3d_engine_loaded_state
from ...inference.tts import get_tts_engine_loaded_state


def register_core_routes(app, ctx: AppContext) -> None:
    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "inference-api"}

    @app.get("/api/status")
    async def api_status():
        loop = asyncio.get_running_loop()
        tts_state, tti_state, tt3d_state = await asyncio.gather(
            loop.run_in_executor(None, get_tts_engine_loaded_state),
            loop.run_in_executor(None, get_tti_engine_loaded_state),
            loop.run_in_executor(None, get_tt3d_engine_loaded_state),
        )
        return {
            "status": "running",
            "service": "inference-api",
            "engines": {
                "tts": {
                    "loaded": bool(tts_state.get("loaded")),
                    "engine": tts_state.get("engine", "SuperTonic 3"),
                },
                "tti": {
                    "loaded": bool(tti_state.get("loaded")),
                    "engine": tti_state.get("engine", "SDXL Base 1"),
                },
                "tt3d": {
                    "loaded": bool(tt3d_state.get("loaded")),
                    "engine": tt3d_state.get("engine", "Hunyuan3D 2.1"),
                },
            },
        }

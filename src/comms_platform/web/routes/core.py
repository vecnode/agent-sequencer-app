import asyncio

from ..context import AppContext


def register_core_routes(app, ctx: AppContext) -> None:
    service = ctx.inference_service
    assert service is not None

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "inference-api"}

    @app.get("/api/status")
    async def api_status():
        tts_state, tti_state, tt3d_state = await asyncio.gather(
            service.tts_loaded_state(),
            service.tti_status(),
            service.tt3d_status(),
        )
        scheduler = service.scheduler
        return {
            "status": "running",
            "service": "inference-api",
            "architecture": "in-process" if service.in_process else "worker-processes",
            "gpu_scheduler": {
                "pending_jobs": scheduler.pending_gpu_jobs if scheduler else 0,
                "serializes": ["tti", "tt3d"],
            },
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
                    "mode": tt3d_state.get("mode", "shape-only"),
                },
            },
        }

from fastapi.responses import FileResponse, JSONResponse

from ...constants import PROJECT_ROOT


def register_media_routes(app) -> None:
    @app.get("/api/media/tti/latest")
    async def media_tti_latest():
        latest_path = PROJECT_ROOT / "output" / "tti_latest.png"
        if not latest_path.exists():
            return JSONResponse(status_code=404, content={"ok": False, "error": "tti_latest_not_found"})
        return FileResponse(latest_path, media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.get("/api/media/tts/latest")
    async def media_tts_latest():
        latest_path = PROJECT_ROOT / "output" / "tts_latest.wav"
        if not latest_path.exists():
            return JSONResponse(status_code=404, content={"ok": False, "error": "tts_latest_not_found"})
        return FileResponse(latest_path, media_type="audio/wav", headers={"Cache-Control": "no-store"})

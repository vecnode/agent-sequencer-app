import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ..constants import TTS_DEFAULT_LANG, TTS_DEFAULT_VOICE
from ..services.inference_service import InferenceService
from ..utils.logger import get_logger
from .context import AppContext
from .routes import register_routes

logger = get_logger("web.app")

__all__ = ["create_app"]


def create_app(config=None) -> FastAPI:
    inference_service = InferenceService(config)

    ctx = AppContext(
        config=config,
        inference_service=inference_service,
        tts_default_lang=getattr(config, "TTS_DEFAULT_LANG", None) or TTS_DEFAULT_LANG,
        tts_default_voice=getattr(config, "TTS_DEFAULT_VOICE", None) or TTS_DEFAULT_VOICE,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await inference_service.start()
        yield
        await inference_service.stop()

    app = FastAPI(
        title="inference-api",
        version="0.3.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    register_routes(app, ctx)
    return app

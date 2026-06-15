import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ..constants import (
    TTS_DEFAULT_LANG,
    TTS_DEFAULT_VOICE,
    TTS_PREWARM_ON_STARTUP,
)
from ..inference.tts import prewarm_tts_engine
from ..inference.tt3d import prepare_tt3d_runtime
from ..utils.logger import get_logger
from .context import AppContext
from .routes import register_routes

logger = get_logger("web.app")

__all__ = ["create_app"]


def create_app(config=None) -> FastAPI:
    ctx = AppContext(
        config=config,
        tts_default_lang=getattr(config, "TTS_DEFAULT_LANG", None) or TTS_DEFAULT_LANG,
        tts_default_voice=getattr(config, "TTS_DEFAULT_VOICE", None) or TTS_DEFAULT_VOICE,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, prepare_tt3d_runtime)

        if TTS_PREWARM_ON_STARTUP:
            loop.run_in_executor(None, prewarm_tts_engine)

        yield

    app = FastAPI(
        title="inference-api",
        version="0.2.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    register_routes(app, ctx)
    return app

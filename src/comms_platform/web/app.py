import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ..constants import (
    ENGINES_PRELOAD_ON_STARTUP,
    TTS_DEFAULT_LANG,
    TTS_DEFAULT_VOICE,
)
from ..inference.startup import preload_inference_engines
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
    preload_on_startup = (
        getattr(config, "ENGINES_PRELOAD_ON_STARTUP", ENGINES_PRELOAD_ON_STARTUP)
        if config is not None
        else ENGINES_PRELOAD_ON_STARTUP
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if preload_on_startup:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, preload_inference_engines)
            if result.get("ok"):
                logger.info("Inference engine preload completed successfully.")
            else:
                logger.warning("Inference engine preload completed with failures.")

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

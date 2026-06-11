import asyncio
import logging
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ..constants import (
    OLLAMA_DEFAULT_HOST,
    OLLAMA_DEFAULT_PORT,
    TD_WEB_DEFAULT_HOST,
    TD_WEB_DEFAULT_PORT,
    TTS_DEFAULT_LANG,
    TTS_DEFAULT_VOICE,
    TTS_PREWARM_ON_STARTUP,
)
from ..inference.tts import prewarm_tts_engine
from ..inference.tt3d import prepare_tt3d_runtime
from ..integrations.unreal import UnrealOrchestrator
from ..mcp import create_platform_mcp
from ..transport.event_bus import EventBus, EventBusLogHandler
from ..utils.logger import get_logger
from .constants import STATIC_DIR
from .context import AppContext
from .routes import register_routes

logger = get_logger("web.app")

# Backward-compatible re-export for tests and external imports.
__all__ = ["EventBus", "EventBusLogHandler", "create_app"]


def create_app(event_bus: EventBus, thread_manager, signal_gateway, master_agent, config=None) -> FastAPI:
    td_web_host = getattr(config, "TD_WEB_HOST", None) or TD_WEB_DEFAULT_HOST
    td_web_port = getattr(config, "TD_WEB_PORT", None) or TD_WEB_DEFAULT_PORT
    ollama_host = getattr(config, "OLLAMA_HOST", None) or OLLAMA_DEFAULT_HOST
    ollama_port = getattr(config, "OLLAMA_PORT", None) or OLLAMA_DEFAULT_PORT

    ctx = AppContext(
        event_bus=event_bus,
        thread_manager=thread_manager,
        signal_gateway=signal_gateway,
        master_agent=master_agent,
        config=config,
        ollama_url=f"http://{ollama_host}:{ollama_port}",
        td_web_url=f"http://{td_web_host}:{td_web_port}",
        tts_default_lang=getattr(config, "TTS_DEFAULT_LANG", None) or TTS_DEFAULT_LANG,
        tts_default_voice=getattr(config, "TTS_DEFAULT_VOICE", None) or TTS_DEFAULT_VOICE,
    )
    unreal_orchestrator = UnrealOrchestrator(ctx)
    mcp_server = None
    mcp_enabled = getattr(config, "MCP_ENABLED", True) if config is not None else True
    mcp_mount_path = getattr(config, "MCP_MOUNT_PATH", "/mcp") if config is not None else "/mcp"

    if mcp_enabled:
        mcp_server = create_platform_mcp(ctx)
        mcp_server.settings.streamable_http_path = "/"

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with AsyncExitStack() as stack:
            if mcp_server is not None:
                await stack.enter_async_context(mcp_server.session_manager.run())
                logger.info("MCP Streamable HTTP server enabled at %s", mcp_mount_path)

            root_logger = logging.getLogger()
            event_log_handler = EventBusLogHandler(event_bus)
            event_log_handler.setLevel(logging.INFO)
            event_log_handler.setFormatter(
                logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s")
            )
            root_logger.addHandler(event_log_handler)
            event_bus.attach_loop(asyncio.get_running_loop())
            logger.info("EventBus attached to asyncio loop.")

            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, prepare_tt3d_runtime)

            if TTS_PREWARM_ON_STARTUP:
                loop.run_in_executor(None, prewarm_tts_engine)

            yield

            await unreal_orchestrator.cancel_tasks()
            if master_agent.is_running:
                master_agent.stop()
            thread_manager.kill_all()
            root_logger.removeHandler(event_log_handler)

    app = FastAPI(
        title="communications-platform",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    register_routes(app, ctx, unreal_orchestrator)

    if mcp_server is not None:
        app.mount(mcp_mount_path, mcp_server.streamable_http_app())
        app.state.mcp_mount_path = mcp_mount_path
        app.state.mcp_server = mcp_server

    return app

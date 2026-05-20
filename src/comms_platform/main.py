# Entry point for the sequence-orchestrator platform

import asyncio

import uvicorn

from .agent_coordinator import AgentCoordinator
from .config import Config
from .td_sender import TouchDesignerSender
from .thread_manager import ThreadManager
from .web.app import EventBus, create_app
from .utils.logger import get_logger

logger = get_logger("main")


async def main():
    config = Config()
    event_bus = EventBus()
    thread_manager = ThreadManager()
    td_sender = TouchDesignerSender(config, thread_manager, event_bus)
    agent_coordinator = AgentCoordinator()

    app = create_app(event_bus, thread_manager, td_sender, agent_coordinator)

    logger.info(f"Starting Sequence Orchestrator Platform → http://{config.WEB_HOST}:{config.WEB_PORT}")

    server_config = uvicorn.Config(
        app,
        host=config.WEB_HOST,
        port=config.WEB_PORT,
        log_level="warning",
    )
    server = uvicorn.Server(server_config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())

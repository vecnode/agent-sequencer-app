"""
Copyright (c) vecnode 2026
"""

import asyncio

import uvicorn

from .config import Config
from .web.app import create_app
from .utils.logger import get_logger

logger = get_logger("main")


async def main():
    config = Config()
    app = create_app(config)

    logger.info(f"Starting Inference API -> http://{config.WEB_HOST}:{config.WEB_PORT}")

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

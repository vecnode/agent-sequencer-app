# Entry point for the Montage Sequencer platform

import uvicorn

from .config import Config
from .td_sender import TouchDesignerSender
from .thread_manager import ThreadManager
from .web.app import EventBus, create_app
from .utils.logger import get_logger

logger = get_logger("main")


def main():
    config = Config()
    event_bus = EventBus()
    thread_manager = ThreadManager()
    td_sender = TouchDesignerSender(config, thread_manager, event_bus)

    app = create_app(event_bus, thread_manager, td_sender)

    logger.info(f"Starting Montage Platform → http://{config.WEB_HOST}:{config.WEB_PORT}")
    uvicorn.run(app, host=config.WEB_HOST, port=config.WEB_PORT, log_level="warning")


if __name__ == "__main__":
    main()

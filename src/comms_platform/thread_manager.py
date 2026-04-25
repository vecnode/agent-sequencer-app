import threading
import time
from typing import Callable, Dict
from .utils.logger import get_logger

logger = get_logger("ThreadManager")

class ThreadManager:
    def __init__(self):
        self.threads: Dict[str, threading.Thread] = {}
        self.stop_events: Dict[str, threading.Event] = {}
        self.lock = threading.Lock()

    def register(self, name: str, target: Callable, daemon: bool = True, *args, **kwargs):
        stop_event = threading.Event()
        def thread_target(*args, **kwargs):
            target(stop_event, *args, **kwargs)
        thread = threading.Thread(target=thread_target, args=args, kwargs=kwargs, daemon=daemon, name=name)
        with self.lock:
            self.threads[name] = thread
            self.stop_events[name] = stop_event
        thread.start()
        logger.info(f"Thread '{name}' registered and started.")

    def kill(self, name: str, timeout: float = 5.0):
        with self.lock:
            stop_event = self.stop_events.get(name)
            thread = self.threads.get(name)
        if stop_event and thread:
            stop_event.set()
            thread.join(timeout)
            if thread.is_alive():
                logger.warning(f"Thread '{name}' did not terminate in time.")
            else:
                logger.info(f"Thread '{name}' terminated.")
            with self.lock:
                self.threads.pop(name, None)
                self.stop_events.pop(name, None)

    def kill_all(self):
        logger.info("Killing all threads...")
        with self.lock:
            names = list(self.threads.keys())
        for name in names:
            self.kill(name)

    def health_check(self):
        with self.lock:
            for name, thread in list(self.threads.items()):
                if not thread.is_alive():
                    logger.warning(f"Thread '{name}' is dead. Restarting...")
                    # Optionally restart or handle dead thread
                    self.threads.pop(name)
                    self.stop_events.pop(name)

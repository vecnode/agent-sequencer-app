import threading
import time

from .utils.logger import get_logger

logger = get_logger("agent.coordinator")


class AgentCoordinator:
    """Small ON/OFF coordinator that emits a heartbeat once per second."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event: threading.Event | None = None
        self._lock = threading.Lock()
        self._heartbeat_count = 0
        self._broadcast_enabled = False

    def start(self) -> bool:
        """Start the agent loop. Returns False when already running."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False

            self._stop_event = threading.Event()
            self._thread = threading.Thread(
                target=self._run,
                args=(self._stop_event,),
                daemon=True,
                name="agent-coordinator",
            )
            self._thread.start()

        logger.info("Agent coordinator started.")
        return True

    def stop(self, timeout: float = 2.0) -> bool:
        """Stop the agent loop. Returns False when it was not running."""
        with self._lock:
            thread = self._thread
            stop_event = self._stop_event
            if not thread or not thread.is_alive() or not stop_event:
                return False
            stop_event.set()

        thread.join(timeout)

        with self._lock:
            self._thread = None
            self._stop_event = None

        logger.info("Agent coordinator stopped.")
        return True

    @property
    def is_running(self) -> bool:
        with self._lock:
            return bool(self._thread and self._thread.is_alive())

    @property
    def heartbeat_count(self) -> int:
        with self._lock:
            return self._heartbeat_count

    @property
    def broadcast_enabled(self) -> bool:
        with self._lock:
            return self._broadcast_enabled

    def set_broadcast(self, enabled: bool) -> bool:
        with self._lock:
            self._broadcast_enabled = enabled
            return self._broadcast_enabled

    def _run(self, stop_event: threading.Event) -> None:
        while not stop_event.wait(1.0):
            # Placeholder processing loop; real receive/process work can be plugged in here.
            with self._lock:
                self._heartbeat_count += 1
                beat = self._heartbeat_count
            logger.info("Agent heartbeat %s", beat)

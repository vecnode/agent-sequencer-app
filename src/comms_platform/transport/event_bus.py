import asyncio
import logging
import threading


class EventBus:
    """Thread-safe broadcast bus that bridges background threads to SSE clients."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def publish(self, data: dict) -> None:
        """Publish an event from any thread to all connected SSE clients."""
        if self._loop is None or not self._loop.is_running():
            return
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            self._loop.call_soon_threadsafe(q.put_nowait, data)

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)


class EventBusLogHandler(logging.Handler):
    """Publish backend log records into the SSE event bus for dashboard terminal output."""

    def __init__(self, event_bus: EventBus) -> None:
        super().__init__()
        self._event_bus = event_bus

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = self.format(record) if self.formatter else record.getMessage()
            self._event_bus.publish(
                {
                    "kind": "log",
                    "logger": record.name,
                    "level": record.levelname,
                    "message": record.getMessage(),
                    "text": text,
                    "timestamp": record.created,
                }
            )
        except Exception:
            return

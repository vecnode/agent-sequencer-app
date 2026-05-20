import asyncio
import json
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..utils.logger import get_logger

logger = get_logger("web.app")

STATIC_DIR = Path(__file__).parent / "static"


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


class SignalPayload(BaseModel):
    address: str
    params: list[Any] = Field(default_factory=list)
    source: str = "external-app"
    protocol: str = "stream"
    direction: str = "inbound"
    target: str = "platform"


def create_app(event_bus: EventBus, thread_manager, signal_gateway, agent_coordinator) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        event_bus.attach_loop(asyncio.get_running_loop())
        logger.info("EventBus attached to asyncio loop.")
        yield
        if agent_coordinator.is_running:
            agent_coordinator.stop()
        thread_manager.kill_all()

    app = FastAPI(
        title="sequence-orchestrator",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return HTMLResponse(
            content=(STATIC_DIR / "index.html").read_text(encoding="utf-8")
        )

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "sequence-orchestrator"}

    @app.get("/api/status")
    async def api_status():
        return {
            "status": "running",
            "sse_clients": event_bus.subscriber_count,
            "osc_output": f"{signal_gateway.osc_output_host}:{signal_gateway.osc_output_port}",
            "osc_input": f"{signal_gateway.osc_input_host}:{signal_gateway.osc_input_port}",
            "agent_running": agent_coordinator.is_running,
            "agent_heartbeats": agent_coordinator.heartbeat_count,
            "agent_broadcast": agent_coordinator.broadcast_enabled,
        }

    @app.post("/api/agent/start")
    async def start_agent():
        started = agent_coordinator.start()
        return {
            "ok": True,
            "started": started,
            "running": agent_coordinator.is_running,
        }

    @app.post("/api/agent/stop")
    async def stop_agent():
        stopped = agent_coordinator.stop()
        return {
            "ok": True,
            "stopped": stopped,
            "running": agent_coordinator.is_running,
        }

    @app.post("/api/agent/broadcast/on")
    async def enable_agent_broadcast():
        enabled = agent_coordinator.set_broadcast(True)
        return {
            "ok": True,
            "broadcast": enabled,
            "running": agent_coordinator.is_running,
        }

    @app.post("/api/agent/broadcast/off")
    async def disable_agent_broadcast():
        enabled = agent_coordinator.set_broadcast(False)
        return {
            "ok": True,
            "broadcast": enabled,
            "running": agent_coordinator.is_running,
        }

    @app.post("/api/signals/publish")
    async def publish_signal(payload: SignalPayload):
        signal_gateway.publish_stream(
            address=payload.address,
            params=payload.params,
            source=payload.source,
            protocol=payload.protocol,
            direction=payload.direction,
            target=payload.target,
        )
        return {"accepted": True}

    @app.post("/api/signals/send")
    async def send_signal(payload: SignalPayload):
        if payload.protocol.lower() == "osc":
            signal_gateway.enqueue(
                address=payload.address,
                params=payload.params,
                source=payload.source,
            )
            return {
                "accepted": True,
                "transport": "osc",
                "target": f"{signal_gateway.osc_output_host}:{signal_gateway.osc_output_port}",
            }

        signal_gateway.publish_stream(
            address=payload.address,
            params=payload.params,
            source=payload.source,
            protocol=payload.protocol,
            direction="outbound",
            target=payload.target,
        )
        return {"accepted": True, "transport": "stream"}

    @app.get("/events")
    async def sse_events():
        async def stream():
            q = event_bus.subscribe()
            try:
                while True:
                    data = await q.get()
                    yield f"data: {json.dumps(data)}\n\n"
            except asyncio.CancelledError:
                pass
            finally:
                event_bus.unsubscribe(q)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    return app

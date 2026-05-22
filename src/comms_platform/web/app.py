import asyncio
import csv
import io
import json
import logging
import os
import socket
import subprocess
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import Body, FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..utils.logger import get_logger

logger = get_logger("web.app")

STATIC_DIR = Path(__file__).parent / "static"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_TOE_PATH = PROJECT_ROOT / "touchdesigner" / "example1.toe"

_TD_WEB_DEFAULT_HOST = os.getenv("TD_WEB_HOST", "127.0.0.1")
_TD_WEB_DEFAULT_PORT = int(os.getenv("TD_WEB_PORT", 9980))
_OLLAMA_DEFAULT_HOST = os.getenv("OLLAMA_HOST", "127.0.0.1")
_OLLAMA_DEFAULT_PORT = int(os.getenv("OLLAMA_PORT", 11434))


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
            # Never let UI streaming failures impact app logging.
            return


class SignalPayload(BaseModel):
    address: str
    params: list[Any] = Field(default_factory=list)
    source: str = "external-app"
    protocol: str = "stream"
    direction: str = "inbound"
    target: str = "platform"


class TdWebPayload(BaseModel):
    payload: dict[str, Any] = Field(default_factory=lambda: {"test_key": "test_value"})
    timeout: float = Field(default=5.0, gt=0, le=30)


class AgentMessagePayload(BaseModel):
    text: str = Field(min_length=1)


def _post_to_td_webserver(url: str, payload: dict, timeout: float) -> dict:
    """Synchronous POST to a TouchDesigner Web Server DAT. Must run in a thread executor."""
    payload_bytes = json.dumps(payload).encode("utf-8")
    req = Request(
        url,
        data=payload_bytes,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            return {
                "ok": True,
                "target": url,
                "payload": payload,
                "status_code": resp.getcode(),
                "response": resp.read().decode("utf-8", errors="replace"),
            }
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
        return {
            "ok": False,
            "target": url,
            "payload": payload,
            "status_code": exc.code,
            "error": str(exc),
            "response": body,
        }
    except (URLError, socket.timeout) as exc:
        return {"ok": False, "target": url, "payload": payload, "error": str(exc)}
    except Exception as exc:
        logger.exception("Unexpected error posting to TouchDesigner webserver: %s", url)
        return {"ok": False, "target": url, "payload": payload, "error": str(exc)}


def _fetch_ollama_status(base_url: str, timeout: float = 3.0) -> dict:
    tags_url = f"{base_url}/api/tags"
    req = Request(tags_url, method="GET")
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
            models = body.get("models", []) if isinstance(body, dict) else []
            return {
                "ok": True,
                "url": base_url,
                "status_code": resp.getcode(),
                "models_count": len(models),
                "models": [m.get("name", "unknown") for m in models if isinstance(m, dict)],
            }
    except Exception as exc:
        return {
            "ok": False,
            "url": base_url,
            "error": str(exc),
            "models_count": 0,
            "models": [],
        }


def _list_touchdesigner_processes() -> dict:
    try:
        processes: list[dict[str, str]] = []

        if os.name == "nt":
            result = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "tasklist command failed")

            for row in csv.reader(io.StringIO(result.stdout)):
                if len(row) < 2:
                    continue
                name = row[0].strip()
                pid = row[1].strip()
                if "touchdesigner" in name.lower():
                    processes.append({"name": name, "pid": pid})
        else:
            result = subprocess.run(
                ["ps", "-axo", "pid=,comm=,args="],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "ps command failed")

            for line in result.stdout.splitlines():
                parts = line.strip().split(maxsplit=2)
                if len(parts) < 3:
                    continue
                pid, command, args = parts
                haystack = f"{command} {args}".lower()
                if "touchdesigner" in haystack:
                    processes.append({"name": command, "pid": pid})

        return {
            "ok": True,
            "running": len(processes) > 0,
            "count": len(processes),
            "processes": processes,
        }
    except Exception as exc:
        return {
            "ok": False,
            "running": False,
            "count": 0,
            "processes": [],
            "error": str(exc),
        }


def create_app(event_bus: EventBus, thread_manager, signal_gateway, agent_coordinator, config=None) -> FastAPI:
    _td_web_host = getattr(config, "TD_WEB_HOST", None) or _TD_WEB_DEFAULT_HOST
    _td_web_port = getattr(config, "TD_WEB_PORT", None) or _TD_WEB_DEFAULT_PORT
    _td_web_url = f"http://{_td_web_host}:{_td_web_port}"
    _ollama_host = getattr(config, "OLLAMA_HOST", None) or _OLLAMA_DEFAULT_HOST
    _ollama_port = getattr(config, "OLLAMA_PORT", None) or _OLLAMA_DEFAULT_PORT
    _ollama_url = f"http://{_ollama_host}:{_ollama_port}"

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        root_logger = logging.getLogger()
        event_log_handler = EventBusLogHandler(event_bus)
        event_log_handler.setLevel(logging.INFO)
        event_log_handler.setFormatter(
            logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s")
        )
        root_logger.addHandler(event_log_handler)
        event_bus.attach_loop(asyncio.get_running_loop())
        logger.info("EventBus attached to asyncio loop.")
        yield
        if agent_coordinator.is_running:
            agent_coordinator.stop()
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

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return HTMLResponse(
            content=(STATIC_DIR / "index.html").read_text(encoding="utf-8")
        )

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "communications-platform"}

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

    @app.post("/api/agent/message")
    async def send_agent_message(payload: AgentMessagePayload):
        reply = agent_coordinator.handle_human_message(payload.text)
        return {
            "ok": True,
            "reply": reply,
            "history_size": len(agent_coordinator.history_text_read),
        }

    @app.post("/api/touchdesigner/run-example")
    async def run_touchdesigner_example():
        toe_path = EXAMPLE_TOE_PATH.resolve()
        if not toe_path.exists():
            return {
                "ok": False,
                "error": "TouchDesigner file not found.",
                "path": str(toe_path),
            }

        try:
            if hasattr(os, "startfile"):
                os.startfile(str(toe_path))  # type: ignore[attr-defined]
            elif os.name == "posix":
                opener = "open" if Path("/usr/bin/open").exists() else "xdg-open"
                subprocess.Popen([opener, str(toe_path)])
            else:
                raise RuntimeError("Unsupported operating system for launching .toe files")
        except Exception as exc:
            logger.exception("Failed to launch TouchDesigner file: %s", toe_path)
            return {
                "ok": False,
                "error": str(exc),
                "path": str(toe_path),
            }

        return {
            "ok": True,
            "path": str(toe_path),
        }

    @app.post("/api/touchdesigner/send-test-data")
    async def send_touchdesigner_test_data(body: TdWebPayload = Body(default=None)):
        if body is None:
            body = TdWebPayload()
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, _post_to_td_webserver, _td_web_url, body.payload, body.timeout
        )
        logger.info(
            "TD webserver POST [%s] → %s",
            _td_web_url,
            "ok" if result["ok"] else f"error: {result.get('error')}",
        )
        return result

    @app.get("/api/touchdesigner/processes")
    async def list_touchdesigner_processes():
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _list_touchdesigner_processes)

    @app.get("/api/ollama/status")
    async def get_ollama_status():
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _fetch_ollama_status, _ollama_url)

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

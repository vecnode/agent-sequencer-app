import asyncio
import io
import json
import logging
import os
import socket
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

import httpx
from fastapi import Body, FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .schemas import (
    AgentMessagePayload,
    SdxlGeneratePayload,
    SendToUnrealPayload,
    SignalPayload,
    TdWebPayload,
    TtsPayload,
    UnrealEventPayload,
)
from .services_ollama import (
    generate_ollama_reply as _generate_ollama_reply,
    open_ollama_application as _open_ollama_application,
)
from .services_sdxl import (
    generate_sdxl_image as _generate_sdxl_image,
    get_sdxl_engine_loaded_state as _get_sdxl_engine_loaded_state,
    set_sdxl_engine_loaded as _set_sdxl_engine_loaded,
)
from .services_touchdesigner import (
    list_touchdesigner_processes as _list_touchdesigner_processes,
    play_audio_file as _play_audio_file,
)
from .services_tts import (
    check_tts_engine_status as _check_tts_engine_status,
    get_tts_engine_loaded_state as _get_tts_engine_loaded_state,
    prewarm_tts_engine as _prewarm_tts_engine,
    set_tts_engine_loaded as _set_tts_engine_loaded,
    synthesize_tts_audio_bytes as _synthesize_tts_audio_bytes,
)
from ..utils.logger import get_logger

logger = get_logger("web.app")

STATIC_DIR = Path(__file__).parent / "static"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_TOE_PATH = PROJECT_ROOT / "touchdesigner" / "example1.toe"

_TD_WEB_DEFAULT_HOST = os.getenv("TD_WEB_HOST", "127.0.0.1")
_TD_WEB_DEFAULT_PORT = int(os.getenv("TD_WEB_PORT", 9980))
_OLLAMA_DEFAULT_HOST = os.getenv("OLLAMA_HOST", "127.0.0.1")
_OLLAMA_DEFAULT_PORT = int(os.getenv("OLLAMA_PORT", 11434))
_TTS_DEFAULT_LANG = os.getenv("TTS_DEFAULT_LANG", "en")
_TTS_DEFAULT_VOICE = os.getenv("TTS_DEFAULT_VOICE", "F1")
_TTS_PREWARM_ON_STARTUP = os.getenv("TTS_PREWARM_ON_STARTUP", "false").lower() == "true"
_SDXL_MODEL_ID = os.getenv("SDXL_MODEL_ID", "stabilityai/stable-diffusion-xl-base-1.0")
_SDXL_DEFAULT_GUIDANCE = float(os.getenv("SDXL_DEFAULT_GUIDANCE", "7.0"))
_SDXL_DEFAULT_STEPS = int(os.getenv("SDXL_DEFAULT_STEPS", "20"))
_TTS_TEST_PROMPT = "hello world"
_SDXL_TEST_PROMPT = "a beautiful sunny city with cars"


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


def create_app(event_bus: EventBus, thread_manager, signal_gateway, master_agent, config=None) -> FastAPI:
    _td_web_host = getattr(config, "TD_WEB_HOST", None) or _TD_WEB_DEFAULT_HOST
    _td_web_port = getattr(config, "TD_WEB_PORT", None) or _TD_WEB_DEFAULT_PORT
    _td_web_url = f"http://{_td_web_host}:{_td_web_port}"
    _ollama_host = getattr(config, "OLLAMA_HOST", None) or _OLLAMA_DEFAULT_HOST
    _ollama_port = getattr(config, "OLLAMA_PORT", None) or _OLLAMA_DEFAULT_PORT
    _ollama_url = f"http://{_ollama_host}:{_ollama_port}"
    _startup_prompt = "Give me four sentences about the root of the mind."
    _startup_tts_lang = getattr(config, "TTS_DEFAULT_LANG", None) or _TTS_DEFAULT_LANG
    _startup_tts_voice = getattr(config, "TTS_DEFAULT_VOICE", None) or _TTS_DEFAULT_VOICE
    _startup_selected_model: str | None = None
    _startup_narration_task: asyncio.Task | None = None

    async def _run_agent_startup_narration(trigger: str) -> None:
        try:
            # Align with the first heartbeat window.
            await asyncio.sleep(1.0)
            if not master_agent.is_running:
                logger.info("Startup narration skipped: agent stopped before execution (trigger=%s).", trigger)
                return

            loop = asyncio.get_running_loop()
            ollama_result = await loop.run_in_executor(
                None,
                _generate_ollama_reply,
                _ollama_url,
                _startup_prompt,
                _startup_selected_model,
            )
            if not ollama_result.get("ok"):
                logger.warning(
                    "Startup narration Ollama step failed (trigger=%s): %s",
                    trigger,
                    ollama_result.get("error"),
                )
                return

            reply_text = str(ollama_result.get("reply", "")).strip()
            if not reply_text:
                logger.warning("Startup narration produced empty text (trigger=%s).", trigger)
                return

            tts_result = await loop.run_in_executor(
                None,
                _synthesize_tts_audio_bytes,
                reply_text,
                _startup_tts_lang,
                _startup_tts_voice,
            )
            if not tts_result.get("ok"):
                logger.warning(
                    "Startup narration TTS step failed (trigger=%s): %s",
                    trigger,
                    tts_result.get("error"),
                )
                return

            output_dir = PROJECT_ROOT / "output"
            output_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            output_path = output_dir / f"agent_startup_{ts}.wav"
            latest_path = output_dir / "agent_startup_latest.wav"
            audio_bytes = tts_result["audio_bytes"]
            output_path.write_bytes(audio_bytes)
            latest_path.write_bytes(audio_bytes)

            play_result = await loop.run_in_executor(None, _play_audio_file, latest_path)
            if not play_result.get("ok"):
                logger.warning(
                    "Startup narration audio saved but playback failed: %s",
                    play_result.get("error"),
                )

            logger.info(
                "Startup narration ready: model=%s voice=%s duration=%.2fs file=%s latest=%s player=%s",
                ollama_result.get("model"),
                tts_result.get("voice_name"),
                float(tts_result.get("duration", 0.0)),
                output_path,
                latest_path,
                play_result.get("player", "none"),
            )

            event_bus.publish(
                {
                    "kind": "stream",
                    "address": "/agent/startup/audio",
                    "params": [str(output_path), ollama_result.get("model", ""), reply_text],
                    "source": "platform",
                    "protocol": "internal",
                    "direction": "outbound",
                }
            )
        except asyncio.CancelledError:
            logger.info("Startup narration task cancelled.")
            raise
        except Exception:
            logger.exception("Unexpected startup narration failure.")

    def _schedule_agent_startup_narration(trigger: str) -> None:
        nonlocal _startup_narration_task
        if _startup_narration_task is not None and not _startup_narration_task.done():
            _startup_narration_task.cancel()
        _startup_narration_task = asyncio.create_task(_run_agent_startup_narration(trigger))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal _startup_narration_task
        root_logger = logging.getLogger()
        event_log_handler = EventBusLogHandler(event_bus)
        event_log_handler.setLevel(logging.INFO)
        event_log_handler.setFormatter(
            logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s")
        )
        root_logger.addHandler(event_log_handler)
        event_bus.attach_loop(asyncio.get_running_loop())
        logger.info("EventBus attached to asyncio loop.")

        if _TTS_PREWARM_ON_STARTUP:
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, _prewarm_tts_engine)

        yield
        if _startup_narration_task is not None and not _startup_narration_task.done():
            _startup_narration_task.cancel()
            try:
                await _startup_narration_task
            except asyncio.CancelledError:
                pass
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
            "agent_running": master_agent.is_running,
            "agent_heartbeats": master_agent.heartbeat_count,
        }

    @app.post("/api/unreal/event")
    async def ingest_unreal_event(payload: UnrealEventPayload):
        request_id = str(uuid4())

        if master_agent.is_running:
            agent_action = "stop"
            agent_changed = master_agent.stop()
        else:
            agent_action = "start"
            agent_changed = master_agent.start()

        agent_running = master_agent.is_running

        logger.info(
            "Unreal event [%s] source=%s event=%s session_id=%s",
            request_id,
            payload.source,
            payload.event,
            payload.session_id or "none",
        )
        logger.info(
            "Agent toggled by Unreal event [%s]: action=%s changed=%s running=%s",
            request_id,
            agent_action,
            agent_changed,
            agent_running,
        )

        event_bus.publish(
            {
                # SSE stream display fields (read by frontend incoming-signals panel)
                "kind": "unreal_event",
                "address": f"/unreal/{payload.event}",
                "params": [payload.message] if payload.message else [],
                "protocol": "unreal",
                "direction": "inbound",
                "source": payload.source,
                # Full Unreal payload preserved for consumers that need it
                "request_id": request_id,
                "event": payload.event,
                "message": payload.message,
                "timestamp_utc": payload.timestamp_utc,
                "session_id": payload.session_id,
                "metadata": payload.metadata,
            }
        )

        return {
            "ok": True,
            "accepted": True,
            "request_id": request_id,
            "source": payload.source,
            "event": payload.event,
            "agent_action": agent_action,
            "agent_changed": agent_changed,
            "agent_running": agent_running,
        }

    @app.post("/api/platform/send-to-unreal")
    async def send_to_unreal(payload: SendToUnrealPayload):
        url = f"http://{payload.unreal_host}:{payload.unreal_port}/notify"
        body = {"message": payload.message}
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(url, json=body)
            resp.raise_for_status()
            logger.info("Sent to Unreal /notify: %r -> %d", payload.message, resp.status_code)
            return {"ok": True, "message": payload.message, "unreal_status": resp.status_code}
        except httpx.ConnectError:
            logger.warning("Unreal not reachable at %s", url)
            return JSONResponse(status_code=503, content={"ok": False, "error": "Unreal not reachable", "url": url})
        except httpx.HTTPStatusError as exc:
            logger.warning("Unreal /notify returned %d", exc.response.status_code)
            return JSONResponse(status_code=502, content={"ok": False, "error": f"Unreal returned {exc.response.status_code}"})
        except Exception as exc:
            logger.exception("Unexpected error sending to Unreal")
            return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})

    @app.post("/api/agent/start")
    async def start_agent():
        started = master_agent.start()
        return {
            "ok": True,
            "started": started,
            "running": master_agent.is_running,
        }

    @app.post("/api/agent/stop")
    async def stop_agent():
        stopped = master_agent.stop()
        return {
            "ok": True,
            "stopped": stopped,
            "running": master_agent.is_running,
        }

    @app.post("/api/agent/message")
    async def send_agent_message(payload: AgentMessagePayload):
        nonlocal _startup_selected_model
        if payload.selected_model and payload.selected_model.strip():
            _startup_selected_model = payload.selected_model.strip()

        reply = master_agent.handle_human_message(payload.text, selected_model=payload.selected_model)
        intent = getattr(master_agent, "last_intent_decision", None)
        ollama = {
            "attempted": False,
            "ok": False,
            "model": None,
            "error": None,
        }

        if isinstance(intent, dict) and intent.get("route") == "chat":
            loop = asyncio.get_running_loop()
            ollama_result = await loop.run_in_executor(
                None,
                _generate_ollama_reply,
                _ollama_url,
                payload.text,
                payload.selected_model,
            )
            ollama = {
                "attempted": True,
                "ok": bool(ollama_result.get("ok")),
                "model": ollama_result.get("model"),
                "error": ollama_result.get("error"),
            }
            if ollama_result.get("ok"):
                reply = str(ollama_result.get("reply", "")).strip()
                logger.info("Ollama chat reply generated using model: %s", ollama_result.get("model"))
            else:
                logger.warning("Ollama chat generation unavailable: %s", ollama_result.get("error"))

        return {
            "ok": True,
            "reply": reply,
            "history_size": len(master_agent.history_text_read),
            "intent": intent,
            "ollama": ollama,
        }

    @app.post("/api/tts/synthesize")
    async def synthesize_tts(payload: TtsPayload):
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            _synthesize_tts_audio_bytes,
            payload.text,
            payload.lang,
            payload.voice_name,
        )

        if not result.get("ok"):
            logger.warning("TTS synthesis failed: %s", result.get("error"))
            return JSONResponse(
                status_code=503,
                content={
                    "ok": False,
                    "error": result.get("error", "tts_synthesis_failed"),
                },
            )

        logger.info(
            "TTS synthesis completed: lang=%s voice=%s duration=%.2fs",
            result.get("lang"),
            result.get("voice_name"),
            float(result.get("duration", 0.0)),
        )

        return StreamingResponse(
            io.BytesIO(result["audio_bytes"]),
            media_type="audio/wav",
            headers={
                "X-TTS-Duration": f"{float(result.get('duration', 0.0)):.2f}",
                "X-TTS-Voice": str(result.get("voice_name", "")),
                "X-TTS-Lang": str(result.get("lang", "")),
            },
        )

    @app.post("/api/tts/test")
    async def tts_test_render():
        state = _get_tts_engine_loaded_state()
        if not state.get("loaded"):
            return JSONResponse(
                status_code=409,
                content={
                    "ok": False,
                    "error": "tts_engine_not_loaded",
                    "engine": "SuperTonic 3",
                },
            )

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            _synthesize_tts_audio_bytes,
            _TTS_TEST_PROMPT,
            _TTS_DEFAULT_LANG,
            _TTS_DEFAULT_VOICE,
        )
        if not result.get("ok"):
            return JSONResponse(
                status_code=503,
                content={
                    "ok": False,
                    "error": result.get("error", "tts_test_failed"),
                    "engine": "SuperTonic 3",
                },
            )

        output_dir = PROJECT_ROOT / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"tts_{ts}.wav"
        latest_path = output_dir / "tts_latest.wav"
        audio_bytes = result["audio_bytes"]
        output_path.write_bytes(audio_bytes)
        latest_path.write_bytes(audio_bytes)

        return {
            "ok": True,
            "engine": "SuperTonic 3",
            "prompt": _TTS_TEST_PROMPT,
            "duration_seconds": float(result.get("duration", 0.0)),
            "output_file": str(output_path),
            "latest_file": str(latest_path),
        }

    @app.get("/api/tts/status")
    async def tts_status(voice_name: str = _TTS_DEFAULT_VOICE):
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _check_tts_engine_status, voice_name)
        return result

    @app.post("/api/tts/engine/on")
    async def tts_engine_on():
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _set_tts_engine_loaded, True)
        return result

    @app.post("/api/tts/engine/off")
    async def tts_engine_off():
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _set_tts_engine_loaded, False)
        return result

    @app.get("/api/sdxl/status")
    async def sdxl_status():
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _get_sdxl_engine_loaded_state)
        return result

    @app.post("/api/sdxl/engine/on")
    async def sdxl_engine_on():
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _set_sdxl_engine_loaded, True)
        if result.get("ok"):
            return result
        return JSONResponse(status_code=503, content=result)

    @app.post("/api/sdxl/engine/off")
    async def sdxl_engine_off():
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _set_sdxl_engine_loaded, False)
        return result

    @app.post("/api/sdxl/generate")
    async def sdxl_generate(payload: SdxlGeneratePayload):
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            _generate_sdxl_image,
            payload.prompt,
            payload.guidance_scale,
            payload.num_inference_steps,
            payload.seed,
        )
        if result.get("ok"):
            return result
        return JSONResponse(status_code=503, content=result)

    @app.post("/api/sdxl/test")
    async def sdxl_test_render():
        state = _get_sdxl_engine_loaded_state()
        if not state.get("loaded"):
            return JSONResponse(
                status_code=409,
                content={
                    "ok": False,
                    "error": "sdxl_engine_not_loaded",
                    "engine": "SDXL Base 1",
                },
            )

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            _generate_sdxl_image,
            _SDXL_TEST_PROMPT,
            _SDXL_DEFAULT_GUIDANCE,
            _SDXL_DEFAULT_STEPS,
            None,
        )
        if result.get("ok"):
            result["prompt"] = _SDXL_TEST_PROMPT
            return result
        return JSONResponse(status_code=503, content=result)

    @app.get("/api/media/sdxl/latest")
    async def media_sdxl_latest():
        latest_path = PROJECT_ROOT / "output" / "sdxl_latest.png"
        if not latest_path.exists():
            return JSONResponse(status_code=404, content={"ok": False, "error": "sdxl_latest_not_found"})
        return FileResponse(latest_path, media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.get("/api/media/tts/latest")
    async def media_tts_latest():
        latest_path = PROJECT_ROOT / "output" / "tts_latest.wav"
        if not latest_path.exists():
            return JSONResponse(status_code=404, content={"ok": False, "error": "tts_latest_not_found"})
        return FileResponse(latest_path, media_type="audio/wav", headers={"Cache-Control": "no-store"})

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

    @app.post("/api/ollama/open")
    async def open_ollama():
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _open_ollama_application)
        if result.get("ok"):
            return result
        return JSONResponse(status_code=503, content=result)

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

import asyncio
import csv
import io
import json
import logging
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import warnings
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

import httpx
import numpy as np
from fastapi import Body, FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from PIL import Image

from ..utils.logger import get_logger

logger = get_logger("web.app")
warnings.filterwarnings(
    "ignore",
    message=r"`upcast_vae` is deprecated and will be removed in version 1\.0\.0\..*",
    category=FutureWarning,
)

STATIC_DIR = Path(__file__).parent / "static"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_TOE_PATH = PROJECT_ROOT / "touchdesigner" / "example1.toe"

_TD_WEB_DEFAULT_HOST = os.getenv("TD_WEB_HOST", "127.0.0.1")
_TD_WEB_DEFAULT_PORT = int(os.getenv("TD_WEB_PORT", 9980))
_OLLAMA_DEFAULT_HOST = os.getenv("OLLAMA_HOST", "127.0.0.1")
_OLLAMA_DEFAULT_PORT = int(os.getenv("OLLAMA_PORT", 11434))
_TTS_DEFAULT_LANG = os.getenv("TTS_DEFAULT_LANG", "en")
_TTS_DEFAULT_VOICE = os.getenv("TTS_DEFAULT_VOICE", "F1")
_TTS_PREWARM_ON_STARTUP = os.getenv("TTS_PREWARM_ON_STARTUP", "true").lower() == "true"
_SDXL_MODEL_ID = os.getenv("SDXL_MODEL_ID", "stabilityai/stable-diffusion-xl-base-1.0")
_SDXL_DEFAULT_GUIDANCE = float(os.getenv("SDXL_DEFAULT_GUIDANCE", "7.0"))
_SDXL_DEFAULT_STEPS = int(os.getenv("SDXL_DEFAULT_STEPS", "20"))
_TTS_TEST_PROMPT = "hello world"
_SDXL_TEST_PROMPT = "a beautiful sunny city with cars"

_tts_engine: Any | None = None
_tts_engine_lock = threading.Lock()
_sdxl_pipeline: Any | None = None
_sdxl_engine_lock = threading.RLock()


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
    selected_model: str | None = None


class TtsPayload(BaseModel):
    text: str = Field(min_length=1)
    lang: str = Field(default=_TTS_DEFAULT_LANG, min_length=2, max_length=8)
    voice_name: str = Field(default=_TTS_DEFAULT_VOICE, min_length=1, max_length=32)


class SdxlGeneratePayload(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    guidance_scale: float = Field(default=_SDXL_DEFAULT_GUIDANCE, ge=1.0, le=20.0)
    num_inference_steps: int = Field(default=_SDXL_DEFAULT_STEPS, ge=5, le=75)
    seed: int | None = Field(default=None, ge=0, le=4294967295)


class UnrealEventPayload(BaseModel):
    source: str = Field(default="unreal", min_length=1, max_length=64)
    event: str = Field(min_length=1, max_length=128)
    message: str = Field(default="", max_length=2048)
    timestamp_utc: str = Field(default="")
    session_id: str | None = Field(default=None, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SendToUnrealPayload(BaseModel):
    message: str = Field(default="Hello from platform", max_length=2048)
    unreal_host: str = Field(default="127.0.0.1", max_length=255)
    unreal_port: int = Field(default=30080, ge=1024, le=65535)


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


def _resolve_ollama_executable() -> Path | None:
    candidates: list[Path] = []
    which_path = shutil.which("ollama")
    if which_path:
        candidates.append(Path(which_path))

    local_appdata = os.getenv("LOCALAPPDATA")
    if local_appdata:
        candidates.extend(
            [
                Path(local_appdata) / "Programs" / "Ollama" / "ollama.exe",
                Path(local_appdata) / "Programs" / "Ollama" / "ollama",
            ]
        )

    program_files = os.getenv("PROGRAMFILES")
    if program_files:
        candidates.extend(
            [
                Path(program_files) / "Ollama" / "ollama.exe",
                Path(program_files) / "Ollama" / "ollama",
            ]
        )

    program_files_x86 = os.getenv("PROGRAMFILES(X86)")
    if program_files_x86:
        candidates.extend(
            [
                Path(program_files_x86) / "Ollama" / "ollama.exe",
                Path(program_files_x86) / "Ollama" / "ollama",
            ]
        )

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _open_ollama_application() -> dict:
    ollama_exe = _resolve_ollama_executable()
    if ollama_exe is None:
        return {
            "ok": False,
            "error": "ollama_not_installed",
        }

    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            [str(ollama_exe), "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(ollama_exe.parent),
            creationflags=creationflags,
        )
        return {
            "ok": True,
            "opened": True,
            "path": str(ollama_exe),
            "command": "serve",
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "path": str(ollama_exe),
        }


def _generate_ollama_reply(
    base_url: str,
    prompt: str,
    selected_model: str | None = None,
    timeout: float = 20.0,
) -> dict:
    status = _fetch_ollama_status(base_url, timeout=min(timeout, 5.0))
    if not status.get("ok"):
        return {
            "ok": False,
            "error": status.get("error", "ollama_unreachable"),
            "model": None,
            "reply": None,
        }

    models = status.get("models", [])
    model_name = (selected_model or "").strip() or (models[0] if models else "")
    if not model_name:
        return {
            "ok": False,
            "error": "no_ollama_models_available",
            "model": None,
            "reply": None,
        }

    generate_url = f"{base_url}/api/generate"
    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
    }
    req = Request(
        generate_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
            reply = str(body.get("response", "")).strip()
            if not reply:
                return {
                    "ok": False,
                    "error": "ollama_empty_response",
                    "model": model_name,
                    "reply": None,
                }
            return {
                "ok": True,
                "error": None,
                "model": model_name,
                "reply": reply,
            }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "model": model_name,
            "reply": None,
        }


def _get_tts_engine() -> Any:
    global _tts_engine
    with _tts_engine_lock:
        if _tts_engine is None:
            from supertonic import TTS

            _tts_engine = TTS(auto_download=True)
            logger.info("Supertonic TTS engine initialized.")
        return _tts_engine


def _set_tts_engine_loaded(loaded: bool) -> dict:
    global _tts_engine
    with _tts_engine_lock:
        if loaded:
            if _tts_engine is None:
                from supertonic import TTS

                _tts_engine = TTS(auto_download=True)
                logger.info("Supertonic TTS engine initialized.")
            return {"ok": True, "engine": "SuperTonic 3", "loaded": True}

        # Best-effort cleanup for SDKs that expose a close/release method.
        if _tts_engine is not None:
            close_fn = getattr(_tts_engine, "close", None)
            if callable(close_fn):
                try:
                    close_fn()
                except Exception:
                    pass
        _tts_engine = None
        return {"ok": True, "engine": "SuperTonic 3", "loaded": False}


def _get_tts_engine_loaded_state() -> dict:
    with _tts_engine_lock:
        return {
            "ok": True,
            "engine": "SuperTonic 3",
            "loaded": _tts_engine is not None,
        }


def _coerce_duration_seconds(value: Any) -> float:
    """Best-effort conversion for SDK duration outputs (float, numpy scalar, or arrays)."""
    try:
        return float(value)
    except Exception:
        pass

    # Handle numpy-like scalars/arrays without importing numpy.
    item_fn = getattr(value, "item", None)
    if callable(item_fn):
        try:
            return float(item_fn())
        except Exception:
            pass

    tolist_fn = getattr(value, "tolist", None)
    if callable(tolist_fn):
        try:
            list_value = tolist_fn()
            if isinstance(list_value, list) and list_value:
                return float(list_value[0])
            return float(list_value)
        except Exception:
            pass


def _sanitize_sdxl_image(image_data: Any) -> Image.Image:
    """Clamp SDXL output to finite RGB pixel values before saving."""
    array = np.asarray(image_data, dtype=np.float32)
    array = np.nan_to_num(array, nan=0.0, posinf=1.0, neginf=0.0)
    array = np.clip(array, 0.0, 1.0)
    if array.ndim == 2:
        array = np.stack([array, array, array], axis=-1)
    if array.ndim == 3 and array.shape[-1] > 3:
        array = array[..., :3]
    if array.ndim != 3 or array.shape[-1] != 3:
        raise ValueError(f"Unexpected SDXL image shape: {array.shape}")
    return Image.fromarray((array * 255.0).round().astype(np.uint8), mode="RGB")

    if isinstance(value, (list, tuple)) and value:
        try:
            return float(value[0])
        except Exception:
            pass

    return 0.0


def _synthesize_tts_audio_bytes(text: str, lang: str, voice_name: str) -> dict:
    try:
        tts = _get_tts_engine()
        style = tts.get_voice_style(voice_name=voice_name)
        wav, duration = tts.synthesize(text, voice_style=style, lang=lang)

        fd, temp_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            tts.save_audio(wav, temp_path)
            audio_bytes = Path(temp_path).read_bytes()
        finally:
            try:
                os.remove(temp_path)
            except OSError:
                pass

        return {
            "ok": True,
            "audio_bytes": audio_bytes,
            "duration": _coerce_duration_seconds(duration),
            "voice_name": voice_name,
            "lang": lang,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
        }


def _prewarm_tts_engine() -> None:
    try:
        _get_tts_engine()
        logger.info("Supertonic TTS prewarm completed.")
    except Exception as exc:
        logger.warning("Supertonic TTS prewarm failed: %s", exc)


def _check_tts_engine_status(voice_name: str) -> dict:
    try:
        state = _get_tts_engine_loaded_state()
        return {
            "ok": True,
            "engine": state["engine"],
            "loaded": state["loaded"],
            "voice_name": voice_name,
        }
    except Exception as exc:
        return {
            "ok": False,
            "engine": "SuperTonic 3",
            "voice_name": voice_name,
            "error": str(exc),
        }


def _get_sdxl_runtime() -> tuple[Any, str, Any, str | None]:
    import torch

    # Prefer CUDA first for SDXL, but gracefully fall back to CPU if unavailable.
    fallback_reason: str | None = None
    if torch.cuda.is_available():
        try:
            _ = torch.empty(1, device="cuda")
            return torch, "cuda", torch.float16, None
        except Exception as exc:
            fallback_reason = f"cuda_probe_failed: {exc}"
    else:
        fallback_reason = "torch.cuda.is_available() is false"

    return torch, "cpu", torch.float32, fallback_reason


def _release_cuda_cache() -> None:
    try:
        import gc

        gc.collect()
    except Exception:
        pass

    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def _get_sdxl_pipeline() -> Any:
    global _sdxl_pipeline
    with _sdxl_engine_lock:
        if _sdxl_pipeline is None:
            xformers_logger = logging.getLogger("xformers")
            previous_xformers_level = xformers_logger.level
            xformers_logger.setLevel(logging.ERROR)
            try:
                from diffusers import DiffusionPipeline

                torch, device, dtype, fallback_reason = _get_sdxl_runtime()
                logger.info(
                    "SDXL runtime probe: torch=%s torch_cuda=%s torch_version_cuda=%s",
                    getattr(torch, "__version__", "unknown"),
                    torch.cuda.is_available(),
                    getattr(getattr(torch, "version", None), "cuda", None),
                )
                logger.info("Initializing SDXL Base 1 pipeline on %s (first load may take several minutes).", device)
                if device == "cpu" and fallback_reason:
                    logger.warning("SDXL CUDA not active, using CPU (%s)", fallback_reason)
                _sdxl_pipeline = DiffusionPipeline.from_pretrained(_SDXL_MODEL_ID, torch_dtype=dtype)
                _sdxl_pipeline = _sdxl_pipeline.to(device)
                _sdxl_pipeline.set_progress_bar_config(disable=True)
                if device == "cuda":
                    try:
                        _sdxl_pipeline.enable_xformers_memory_efficient_attention()
                        logger.info("SDXL xFormers attention enabled.")
                    except Exception:
                        logger.info("SDXL xFormers attention unavailable; using default attention.")
                    try:
                        import torch

                        _sdxl_pipeline.unet.to(memory_format=torch.channels_last)
                    except Exception:
                        pass
                logger.info("SDXL Base 1 pipeline initialized on %s.", device)
            finally:
                xformers_logger.setLevel(previous_xformers_level)
        return _sdxl_pipeline


def _set_sdxl_engine_loaded(loaded: bool) -> dict:
    global _sdxl_pipeline
    with _sdxl_engine_lock:
        if loaded:
            try:
                _get_sdxl_pipeline()
                _, device, _, _ = _get_sdxl_runtime()
                return {
                    "ok": True,
                    "engine": "SDXL Base 1",
                    "loaded": True,
                    "model_id": _SDXL_MODEL_ID,
                    "device": device,
                }
            except Exception as exc:
                return {
                    "ok": False,
                    "engine": "SDXL Base 1",
                    "loaded": False,
                    "model_id": _SDXL_MODEL_ID,
                    "error": str(exc),
                }

        _sdxl_pipeline = None
        _release_cuda_cache()
        _, device, _, _ = _get_sdxl_runtime()
        return {
            "ok": True,
            "engine": "SDXL Base 1",
            "loaded": False,
            "model_id": _SDXL_MODEL_ID,
            "device": device,
        }


def _get_sdxl_engine_loaded_state() -> dict:
    with _sdxl_engine_lock:
        _, device, _, _ = _get_sdxl_runtime()
        return {
            "ok": True,
            "engine": "SDXL Base 1",
            "loaded": _sdxl_pipeline is not None,
            "model_id": _SDXL_MODEL_ID,
            "device": device,
        }


def _generate_sdxl_image(prompt: str, guidance_scale: float, num_inference_steps: int, seed: int | None) -> dict:
    try:
        prompt = str(prompt or "").strip()
        if not prompt:
            return {
                "ok": False,
                "error": "prompt_required",
                "engine": "SDXL Base 1",
            }

        torch, device, _, _ = _get_sdxl_runtime()
        generator = None
        if seed is not None:
            generator = torch.Generator(device=device).manual_seed(int(seed))

        started_at = datetime.now(timezone.utc)
        pipeline = _get_sdxl_pipeline()
        with torch.inference_mode():
            image_result = pipeline(
                prompt=prompt,
                guidance_scale=float(guidance_scale),
                num_inference_steps=int(num_inference_steps),
                generator=generator,
                output_type="np",
            ).images[0]
        image = _sanitize_sdxl_image(image_result)
        elapsed_seconds = (datetime.now(timezone.utc) - started_at).total_seconds()

        output_dir = PROJECT_ROOT / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"sdxl_{ts}.png"
        latest_path = output_dir / "sdxl_latest.png"
        image.save(output_path, format="PNG")
        image.save(latest_path, format="PNG")

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        import base64

        image_base64 = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("utf-8")

        if device == "cuda":
            torch.cuda.empty_cache()

        return {
            "ok": True,
            "engine": "SDXL Base 1",
            "loaded": True,
            "model_id": _SDXL_MODEL_ID,
            "device": device,
            "image_id": str(uuid4()),
            "image_base64": image_base64,
            "output_file": str(output_path),
            "latest_file": str(latest_path),
            "duration_seconds": elapsed_seconds,
            "guidance_scale": float(guidance_scale),
            "num_inference_steps": int(num_inference_steps),
            "seed": seed,
        }
    except Exception as exc:
        logger.warning("SDXL generation failed: %s", exc)
        return {
            "ok": False,
            "engine": "SDXL Base 1",
            "error": str(exc),
        }


def _play_audio_file(audio_path: Path) -> dict:
    try:
        if not audio_path.exists():
            return {"ok": False, "error": f"audio file not found: {audio_path}"}

        vlc_candidates = [
            Path(r"C:\Program Files\VideoLAN\VLC\vlc.exe"),
            Path(r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe"),
        ]
        for vlc_path in vlc_candidates:
            if vlc_path.exists():
                subprocess.Popen([str(vlc_path), "--play-and-exit", str(audio_path)])
                return {"ok": True, "player": "vlc", "path": str(audio_path)}

        if hasattr(os, "startfile"):
            os.startfile(str(audio_path))  # type: ignore[attr-defined]
            return {"ok": True, "player": "startfile", "path": str(audio_path)}

        if os.name == "posix":
            opener = "open" if Path("/usr/bin/open").exists() else "xdg-open"
            subprocess.Popen([opener, str(audio_path)])
            return {"ok": True, "player": opener, "path": str(audio_path)}

        return {"ok": False, "error": "no audio player available", "path": str(audio_path)}
    except Exception as exc:
        logger.exception("Failed to play audio file: %s", audio_path)
        return {"ok": False, "error": str(exc), "path": str(audio_path)}


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

import json
import os
import shutil
import subprocess
from pathlib import Path
from urllib.request import Request, urlopen


def fetch_ollama_status(base_url: str, timeout: float = 3.0) -> dict:
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


def open_ollama_application() -> dict:
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


def generate_ollama_reply(
    base_url: str,
    prompt: str,
    selected_model: str | None = None,
    timeout: float = 20.0,
) -> dict:
    status = fetch_ollama_status(base_url, timeout=min(timeout, 5.0))
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

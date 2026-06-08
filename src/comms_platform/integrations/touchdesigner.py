import csv
import io
import json
import os
import socket
import subprocess
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..utils.logger import get_logger

logger = get_logger("integrations.touchdesigner")


def post_to_td_webserver(url: str, payload: dict, timeout: float) -> dict:
    """Synchronous POST to a TouchDesigner Web Server DAT. Must run in a thread executor."""
    req = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
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


def list_touchdesigner_processes() -> dict:
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

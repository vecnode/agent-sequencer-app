"""Shared worker subprocess loop."""

from __future__ import annotations

import sys
import traceback
from collections.abc import Callable
from typing import Any

from .protocol import WorkerRequest, WorkerResponse, encode_response


Handler = Callable[[str, dict[str, Any]], dict[str, Any]]


def run_worker_loop(
    *,
    engine_name: str,
    handler: Handler,
    preload: Callable[[], dict[str, Any]] | None = None,
) -> int:
    if preload is not None:
        try:
            preload()
        except Exception as exc:
            print(f"[worker:{engine_name}] preload failed: {exc}", file=sys.stderr, flush=True)

    print(f"[worker:{engine_name}] ready", file=sys.stderr, flush=True)

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue

        try:
            import json

            payload = json.loads(line)
            request = WorkerRequest(
                id=str(payload["id"]),
                method=str(payload["method"]),
                params=dict(payload.get("params") or {}),
            )
            result = handler(request.method, request.params)
            response = WorkerResponse(id=request.id, ok=True, result=result)
        except Exception as exc:
            request_id = "unknown"
            try:
                import json

                request_id = str(json.loads(raw_line).get("id", "unknown"))
            except Exception:
                pass
            traceback.print_exc(file=sys.stderr)
            response = WorkerResponse(id=request_id, ok=False, error=str(exc))

        sys.stdout.write(encode_response(response) + "\n")
        sys.stdout.flush()

    return 0

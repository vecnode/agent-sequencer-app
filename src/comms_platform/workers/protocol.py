"""Line-delimited JSON protocol for inference worker subprocesses."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class WorkerRequest:
    id: str
    method: str
    params: dict[str, Any]


@dataclass(slots=True)
class WorkerResponse:
    id: str
    ok: bool
    result: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"id": self.id, "ok": self.ok}
        if self.result is not None:
            payload["result"] = self.result
        if self.error is not None:
            payload["error"] = self.error
        return payload


def encode_request(request: WorkerRequest) -> str:
    return json.dumps(
        {"id": request.id, "method": request.method, "params": request.params},
        separators=(",", ":"),
    )


def encode_response(response: WorkerResponse) -> str:
    return json.dumps(response.to_dict(), separators=(",", ":"))


def parse_response(line: str) -> WorkerResponse:
    payload = json.loads(line)
    return WorkerResponse(
        id=str(payload["id"]),
        ok=bool(payload.get("ok")),
        result=payload.get("result"),
        error=payload.get("error"),
    )

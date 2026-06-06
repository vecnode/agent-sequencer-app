import json
import os
from urllib.error import URLError
from urllib.request import Request, urlopen

import pytest


BASE_URL = os.getenv("LIVE_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def _post_json(path: str, payload: dict, timeout: float = 5.0) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8")
    req = Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8", errors="replace"))
        return resp.getcode(), body


def _require_live_server() -> None:
    req = Request(f"{BASE_URL}/health", method="GET")
    try:
        with urlopen(req, timeout=2.0) as resp:
            if resp.getcode() != 200:
                pytest.skip(f"Live API not ready at {BASE_URL} (status={resp.getcode()})")
    except URLError:
        pytest.skip(f"Live API not reachable at {BASE_URL}. Start the platform first.")


def test_live_unreal_start_audio_event():
    _require_live_server()
    status, body = _post_json(
        "/api/unreal/event",
        {
            "source": "pytest-live",
            "event": "key_pressed",
            "message": "start audio",
            "session_id": "default",
        },
    )

    print(f"[LIVE] start audio -> status={status} body={body}")
    assert status == 200
    assert body.get("ok") is True
    assert body.get("routed_action") == "start_audio"


def test_live_unreal_start_image_event():
    _require_live_server()
    status, body = _post_json(
        "/api/unreal/event",
        {
            "source": "pytest-live",
            "event": "key_pressed",
            "message": "start image",
            "session_id": "default",
        },
    )

    print(f"[LIVE] start image -> status={status} body={body}")
    assert status == 200
    assert body.get("ok") is True
    assert body.get("routed_action") == "start_image"

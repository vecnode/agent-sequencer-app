from unittest.mock import patch
from urllib.error import URLError

from api_test_support import build_client, log_test


def test_ollama_status_endpoint_success():
    class _StubResponse:
        def __init__(self, body: str, status_code: int = 200):
            self._body = body
            self._status_code = status_code

        def read(self):
            return self._body.encode("utf-8")

        def getcode(self):
            return self._status_code

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    mock_json = '{"models": [{"name": "llama3.2:latest"}]}'
    with build_client() as client:
        with patch("comms_platform.web.app.urlopen", return_value=_StubResponse(mock_json)):
            response = client.get("/api/ollama/status")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["models_count"] == 1
    assert body["models"] == ["llama3.2:latest"]
    log_test(
        "GET /api/ollama/status [success]",
        f"status_code={response.status_code}, ok={body['ok']}, models_count={body['models_count']}",
    )


def test_ollama_status_endpoint_connection_error():
    with build_client() as client:
        with patch("comms_platform.web.app.urlopen", side_effect=URLError("connection refused")):
            response = client.get("/api/ollama/status")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["models_count"] == 0
    log_test(
        "GET /api/ollama/status [connection_error]",
        f"status_code={response.status_code}, ok={body['ok']}, error={body['error']}",
    )

import sys
from unittest.mock import patch

from api_test_support import build_client, log_test


def test_touchdesigner_run_example_endpoint():
    with build_client() as client:
        if hasattr(sys.modules["os"], "startfile"):
            with patch("comms_platform.web.routes.third_party.os.startfile") as mocked_startfile:
                response = client.post("/api/touchdesigner/run-example")
            assert response.status_code == 200
            body = response.json()
            assert body["ok"] is True
            mocked_startfile.assert_called_once()
        else:
            with patch("comms_platform.web.routes.third_party.subprocess.Popen") as mocked_popen:
                response = client.post("/api/touchdesigner/run-example")
            assert response.status_code == 200
            body = response.json()
            assert body["ok"] is True
            mocked_popen.assert_called_once()

        log_test(
            "POST /api/touchdesigner/run-example",
            f"status_code={response.status_code}, ok={body['ok']}, path={body['path']}",
        )


def test_touchdesigner_send_test_data_endpoint_success():
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

    with build_client() as client:
        with patch("comms_platform.integrations.touchdesigner.urlopen", return_value=_StubResponse("ok")) as mocked_urlopen:
            response = client.post("/api/touchdesigner/send-test-data")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["status_code"] == 200
    assert body["payload"] == {"test_key": "test_value"}
    mocked_urlopen.assert_called_once()
    log_test(
        "POST /api/touchdesigner/send-test-data [success]",
        f"status_code={response.status_code}, ok={body['ok']}, target={body['target']}",
    )


def test_touchdesigner_send_test_data_endpoint_connection_error():
    with build_client() as client:
        with patch("comms_platform.integrations.touchdesigner.urlopen", side_effect=Exception("connection refused")):
            response = client.post("/api/touchdesigner/send-test-data")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["payload"] == {"test_key": "test_value"}
    log_test(
        "POST /api/touchdesigner/send-test-data [connection_error]",
        f"status_code={response.status_code}, ok={body['ok']}, target={body['target']}",
    )


def test_touchdesigner_send_test_data_endpoint_custom_payload():
    class _StubResponse:
        def read(self): return b"ok"
        def getcode(self): return 200
        def __enter__(self): return self
        def __exit__(self, *_): return False

    with build_client() as client:
        with patch("comms_platform.integrations.touchdesigner.urlopen", return_value=_StubResponse()):
            response = client.post(
                "/api/touchdesigner/send-test-data",
                json={"payload": {"my_key": "my_value"}, "timeout": 3.0},
            )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["payload"] == {"my_key": "my_value"}
    log_test(
        "POST /api/touchdesigner/send-test-data [custom_payload]",
        f"status_code={response.status_code}, ok={body['ok']}, payload={body['payload']}",
    )


def test_touchdesigner_processes_endpoint_reports_running_processes():
    mock_payload = {
        "ok": True,
        "running": True,
        "count": 2,
        "processes": [
            {"name": "TouchDesigner.exe", "pid": "1200"},
            {"name": "TouchDesigner.exe", "pid": "1301"},
        ],
    }
    with build_client() as client:
        with patch("comms_platform.web.routes.third_party.list_touchdesigner_processes", return_value=mock_payload):
            response = client.get("/api/touchdesigner/processes")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["running"] is True
    assert body["count"] == 2
    assert len(body["processes"]) == 2
    log_test(
        "GET /api/touchdesigner/processes",
        f"status_code={response.status_code}, running={body['running']}, count={body['count']}",
    )

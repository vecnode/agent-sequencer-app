import sys
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from comms_platform.web.app import EventBus, create_app


class StubThreadManager:
    def kill_all(self):
        pass


class StubAgentCoordinator:
    def __init__(self):
        self._running = False
        self.heartbeat_count = 0
        self.broadcast_enabled = False
        self._history_text_read: list[str] = []

    @property
    def is_running(self):
        return self._running

    def start(self):
        if self._running:
            return False
        self._running = True
        return True

    def stop(self):
        if not self._running:
            return False
        self._running = False
        return True

    def set_broadcast(self, enabled: bool):
        self.broadcast_enabled = enabled
        return self.broadcast_enabled

    @property
    def history_text_read(self):
        return list(self._history_text_read)

    def handle_human_message(self, text: str):
        self._history_text_read.append(text.strip())
        return "ok."


class StubSignalGateway:
    osc_output_host = "127.0.0.1"
    osc_output_port = 9000
    osc_input_host = "0.0.0.0"
    osc_input_port = 9001

    def __init__(self):
        self.published: list[dict] = []
        self.enqueued: list[dict] = []

    def publish_stream(self, **kwargs):
        self.published.append(kwargs)

    def enqueue(self, **kwargs):
        self.enqueued.append(kwargs)


def _build_client() -> TestClient:
    app = create_app(
        event_bus=EventBus(),
        thread_manager=StubThreadManager(),
        signal_gateway=StubSignalGateway(),
        master_agent=StubAgentCoordinator(),
    )
    return TestClient(app)


def _log_test(test_name: str, details: str) -> None:
    print(f"[TEST] {test_name} | {details}", flush=True)


def test_health_endpoint_returns_ok():
    with _build_client() as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "communications-platform"}
    body = response.json()
    _log_test(
        "GET /health",
        f"status_code={response.status_code}, status={body['status']}, service={body['service']}",
    )


def test_status_endpoint_reports_server_active():
    with _build_client() as client:
        response = client.get("/api/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "running"
    assert "sse_clients" in body
    assert "osc_input" in body
    assert "osc_output" in body
    assert "agent_broadcast" in body
    _log_test(
        "GET /api/status",
        "status_code="
        f"{response.status_code}, status={body['status']}, clients={body['sse_clients']}, "
        f"osc_in={body['osc_input']}, osc_out={body['osc_output']}",
    )


def test_signals_publish_accepted():
    gateway = StubSignalGateway()
    app = create_app(
        event_bus=EventBus(),
        thread_manager=StubThreadManager(),
        signal_gateway=gateway,
        master_agent=StubAgentCoordinator(),
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/signals/publish",
            json={"address": "/test/publish", "params": [1, 2], "source": "pytest"},
        )

    assert response.status_code == 200
    assert response.json() == {"accepted": True}
    assert len(gateway.published) == 1
    call = gateway.published[0]
    _log_test(
        "POST /api/signals/publish",
        f"status_code={response.status_code}, accepted={response.json()['accepted']}, "
        f"address={call['address']}, params={call['params']}, source={call['source']}",
    )


def test_signals_send_stream_transport():
    gateway = StubSignalGateway()
    app = create_app(
        event_bus=EventBus(),
        thread_manager=StubThreadManager(),
        signal_gateway=gateway,
        master_agent=StubAgentCoordinator(),
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/signals/send",
            json={"address": "/test/stream", "params": [42], "protocol": "stream", "source": "pytest"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["transport"] == "stream"
    assert len(gateway.published) == 1
    _log_test(
        "POST /api/signals/send [stream]",
        f"status_code={response.status_code}, transport={body['transport']}, "
        f"address={gateway.published[0]['address']}, params={gateway.published[0]['params']}",
    )


def test_signals_send_osc_transport():
    gateway = StubSignalGateway()
    app = create_app(
        event_bus=EventBus(),
        thread_manager=StubThreadManager(),
        signal_gateway=gateway,
        master_agent=StubAgentCoordinator(),
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/signals/send",
            json={"address": "/test/osc", "params": [7], "protocol": "osc", "source": "pytest"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["transport"] == "osc"
    assert len(gateway.enqueued) == 1
    call = gateway.enqueued[0]
    _log_test(
        "POST /api/signals/send [osc]",
        f"status_code={response.status_code}, transport={body['transport']}, "
        f"target={body['target']}, address={call['address']}, params={call['params']}",
    )


def test_agent_start_and_stop_endpoints():
    with _build_client() as client:
        start_response = client.post("/api/agent/start")
        assert start_response.status_code == 200
        start_body = start_response.json()
        assert start_body["ok"] is True
        assert start_body["running"] is True

        stop_response = client.post("/api/agent/stop")
        assert stop_response.status_code == 200
        stop_body = stop_response.json()
        assert stop_body["ok"] is True
        assert stop_body["running"] is False

        _log_test(
            "POST /api/agent/start + /api/agent/stop",
            f"start_running={start_body['running']}, stop_running={stop_body['running']}",
        )


def test_agent_broadcast_on_and_off_endpoints():
    with _build_client() as client:
        on_response = client.post("/api/agent/broadcast/on")
        assert on_response.status_code == 200
        on_body = on_response.json()
        assert on_body["ok"] is True
        assert on_body["broadcast"] is True

        off_response = client.post("/api/agent/broadcast/off")
        assert off_response.status_code == 200
        off_body = off_response.json()
        assert off_body["ok"] is True
        assert off_body["broadcast"] is False

        _log_test(
            "POST /api/agent/broadcast/on + /api/agent/broadcast/off",
            f"broadcast_on={on_body['broadcast']}, broadcast_off={off_body['broadcast']}",
        )


def test_agent_message_endpoint_stores_history_and_returns_ok():
    with _build_client() as client:
        response = client.post("/api/agent/message", json={"text": "hello agent"})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["reply"] == "ok."
    assert body["history_size"] == 1
    _log_test(
        "POST /api/agent/message",
        f"status_code={response.status_code}, reply={body['reply']}, history_size={body['history_size']}",
    )


def test_touchdesigner_run_example_endpoint():
    with _build_client() as client:
        if hasattr(sys.modules["os"], "startfile"):
            with patch("comms_platform.web.app.os.startfile") as mocked_startfile:
                response = client.post("/api/touchdesigner/run-example")
            assert response.status_code == 200
            body = response.json()
            assert body["ok"] is True
            mocked_startfile.assert_called_once()
        else:
            with patch("comms_platform.web.app.subprocess.Popen") as mocked_popen:
                response = client.post("/api/touchdesigner/run-example")
            assert response.status_code == 200
            body = response.json()
            assert body["ok"] is True
            mocked_popen.assert_called_once()

        _log_test(
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

    with _build_client() as client:
        with patch("comms_platform.web.app.urlopen", return_value=_StubResponse("ok")) as mocked_urlopen:
            response = client.post("/api/touchdesigner/send-test-data")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["status_code"] == 200
    assert body["payload"] == {"test_key": "test_value"}
    mocked_urlopen.assert_called_once()
    _log_test(
        "POST /api/touchdesigner/send-test-data [success]",
        f"status_code={response.status_code}, ok={body['ok']}, target={body['target']}",
    )


def test_touchdesigner_send_test_data_endpoint_connection_error():
    with _build_client() as client:
        with patch("comms_platform.web.app.urlopen", side_effect=URLError("connection refused")):
            response = client.post("/api/touchdesigner/send-test-data")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["payload"] == {"test_key": "test_value"}
    _log_test(
        "POST /api/touchdesigner/send-test-data [connection_error]",
        f"status_code={response.status_code}, ok={body['ok']}, target={body['target']}",
    )


def test_touchdesigner_send_test_data_endpoint_custom_payload():
    class _StubResponse:
        def read(self): return b"ok"
        def getcode(self): return 200
        def __enter__(self): return self
        def __exit__(self, *_): return False

    with _build_client() as client:
        with patch("comms_platform.web.app.urlopen", return_value=_StubResponse()):
            response = client.post(
                "/api/touchdesigner/send-test-data",
                json={"payload": {"my_key": "my_value"}, "timeout": 3.0},
            )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["payload"] == {"my_key": "my_value"}
    _log_test(
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
    with _build_client() as client:
        with patch("comms_platform.web.app._list_touchdesigner_processes", return_value=mock_payload):
            response = client.get("/api/touchdesigner/processes")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["running"] is True
    assert body["count"] == 2
    assert len(body["processes"]) == 2
    _log_test(
        "GET /api/touchdesigner/processes",
        f"status_code={response.status_code}, running={body['running']}, count={body['count']}",
    )


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
    with _build_client() as client:
        with patch("comms_platform.web.app.urlopen", return_value=_StubResponse(mock_json)):
            response = client.get("/api/ollama/status")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["models_count"] == 1
    assert body["models"] == ["llama3.2:latest"]
    _log_test(
        "GET /api/ollama/status [success]",
        f"status_code={response.status_code}, ok={body['ok']}, models_count={body['models_count']}",
    )


def test_ollama_status_endpoint_connection_error():
    with _build_client() as client:
        with patch("comms_platform.web.app.urlopen", side_effect=URLError("connection refused")):
            response = client.get("/api/ollama/status")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["models_count"] == 0
    _log_test(
        "GET /api/ollama/status [connection_error]",
        f"status_code={response.status_code}, ok={body['ok']}, error={body['error']}",
    )

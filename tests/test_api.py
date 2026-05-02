import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from comms_platform.web.app import EventBus, create_app


class DummyThreadManager:
    def kill_all(self):
        pass


class DummySignalGateway:
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
        thread_manager=DummyThreadManager(),
        signal_gateway=DummySignalGateway(),
    )
    return TestClient(app)


def _log_test(test_name: str, details: str) -> None:
    print(f"[TEST] {test_name} | {details}", flush=True)


def test_health_endpoint_returns_ok():
    with _build_client() as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "sequence-orchestrator"}
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
    _log_test(
        "GET /api/status",
        "status_code="
        f"{response.status_code}, status={body['status']}, clients={body['sse_clients']}, "
        f"osc_in={body['osc_input']}, osc_out={body['osc_output']}",
    )


def test_signals_publish_accepted():
    gateway = DummySignalGateway()
    app = create_app(
        event_bus=EventBus(),
        thread_manager=DummyThreadManager(),
        signal_gateway=gateway,
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
    gateway = DummySignalGateway()
    app = create_app(
        event_bus=EventBus(),
        thread_manager=DummyThreadManager(),
        signal_gateway=gateway,
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
    gateway = DummySignalGateway()
    app = create_app(
        event_bus=EventBus(),
        thread_manager=DummyThreadManager(),
        signal_gateway=gateway,
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

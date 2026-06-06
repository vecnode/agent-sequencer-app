from api_test_support import StubAgentCoordinator, StubSignalGateway, StubThreadManager, build_client, log_test

from comms_platform.web.app import EventBus, create_app


def test_signals_publish_accepted():
    gateway = StubSignalGateway()
    app = create_app(
        event_bus=EventBus(),
        thread_manager=StubThreadManager(),
        signal_gateway=gateway,
        master_agent=StubAgentCoordinator(),
    )
    with __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(app) as client:
        response = client.post(
            "/api/signals/publish",
            json={"address": "/test/publish", "params": [1, 2], "source": "pytest"},
        )

    assert response.status_code == 200
    assert response.json() == {"accepted": True}
    assert len(gateway.published) == 1
    call = gateway.published[0]
    log_test(
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
    with __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(app) as client:
        response = client.post(
            "/api/signals/send",
            json={"address": "/test/stream", "params": [42], "protocol": "stream", "source": "pytest"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["transport"] == "stream"
    assert len(gateway.published) == 1
    log_test(
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
    with __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(app) as client:
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
    log_test(
        "POST /api/signals/send [osc]",
        f"status_code={response.status_code}, transport={body['transport']}, "
        f"target={body['target']}, address={call['address']}, params={call['params']}",
    )

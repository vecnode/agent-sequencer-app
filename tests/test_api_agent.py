from api_test_support import build_client, log_test


def test_unreal_event_endpoint_accepts_payload():
    payload = {
        "source": "unreal-editor",
        "event": "key_pressed",
        "message": "hello world 2",
        "timestamp_utc": "2026-05-25T12:00:00Z",
        "session_id": "characters-local",
        "metadata": {"map": "ThirdPersonMap", "build": "Development"},
    }

    with build_client() as client:
        response = client.post("/api/unreal/event", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["accepted"] is True
    assert body["source"] == payload["source"]
    assert body["event"] == payload["event"]
    assert isinstance(body["request_id"], str)
    assert len(body["request_id"]) > 0
    log_test(
        "POST /api/unreal/event [success]",
        f"status_code={response.status_code}, accepted={body['accepted']}, request_id={body['request_id']}",
    )


def test_unreal_event_endpoint_validates_required_event():
    with build_client() as client:
        response = client.post("/api/unreal/event", json={"source": "unreal-editor", "message": "x"})

    assert response.status_code == 422
    log_test(
        "POST /api/unreal/event [validation_error]",
        f"status_code={response.status_code}",
    )


def test_agent_start_and_stop_endpoints():
    with build_client() as client:
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

        log_test(
            "POST /api/agent/start + /api/agent/stop",
            f"start_running={start_body['running']}, stop_running={stop_body['running']}",
        )


def test_agent_message_endpoint_stores_history_and_returns_ok():
    with build_client() as client:
        response = client.post("/api/agent/message", json={"text": "hello agent"})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["reply"] == "ok."
    assert body["history_size"] == 1
    log_test(
        "POST /api/agent/message",
        f"status_code={response.status_code}, reply={body['reply']}, history_size={body['history_size']}",
    )

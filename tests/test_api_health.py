from api_test_support import build_client, log_test


def test_health_endpoint_returns_ok():
    with build_client() as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "inference-api"}
    body = response.json()
    log_test(
        "GET /health",
        f"status_code={response.status_code}, status={body['status']}, service={body['service']}",
    )


def test_status_endpoint_reports_engine_states():
    with build_client() as client:
        response = client.get("/api/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "running"
    assert body["service"] == "inference-api"
    assert "engines" in body
    assert "tts" in body["engines"]
    assert "tti" in body["engines"]
    assert "tt3d" in body["engines"]
    log_test(
        "GET /api/status",
        f"status_code={response.status_code}, status={body['status']}, "
        f"tts_loaded={body['engines']['tts']['loaded']}",
    )

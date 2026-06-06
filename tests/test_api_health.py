from api_test_support import build_client, log_test


def test_health_endpoint_returns_ok():
    with build_client() as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "communications-platform"}
    body = response.json()
    log_test(
        "GET /health",
        f"status_code={response.status_code}, status={body['status']}, service={body['service']}",
    )


def test_status_endpoint_reports_server_active():
    with build_client() as client:
        response = client.get("/api/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "running"
    assert "sse_clients" in body
    assert "osc_input" in body
    assert "osc_output" in body
    log_test(
        "GET /api/status",
        "status_code="
        f"{response.status_code}, status={body['status']}, clients={body['sse_clients']}, "
        f"osc_in={body['osc_input']}, osc_out={body['osc_output']}",
    )

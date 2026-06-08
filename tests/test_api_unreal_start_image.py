from unittest.mock import patch

from api_test_support import StubAgentCoordinator, StubSignalGateway, StubThreadManager, log_test
from comms_platform.web.app import EventBus, create_app


def test_unreal_event_start_image_routes_to_image_generation():
    app = create_app(
        event_bus=EventBus(),
        thread_manager=StubThreadManager(),
        signal_gateway=StubSignalGateway(),
        master_agent=StubAgentCoordinator(),
    )

    with patch(
        "comms_platform.web.app._generate_tti_image",
        return_value={
            "ok": True,
            "output_file": "output/tti_test.png",
            "latest_file": "output/tti_latest.png",
        },
    ), __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(app) as client:
        response = client.post(
            "/api/unreal/event",
            json={
                "source": "unreal-editor",
                "event": "key_pressed",
                "message": "start image",
                "session_id": "default",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["accepted"] is True
    assert body["routed_action"] == "start_image"
    assert body["route_changed"] is True
    assert body["route_details"]["image_task_running"] is True
    assert body["agent_action"] == "none"
    assert body["agent_running"] is False

    log_test(
        "POST /api/unreal/event [start_image]",
        f"status_code={response.status_code}, routed_action={body['routed_action']}, "
        f"image_task_running={body['route_details']['image_task_running']}",
    )

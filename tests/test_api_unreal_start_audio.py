from unittest.mock import patch

from api_test_support import StubAgentCoordinator, StubSignalGateway, StubThreadManager, log_test
from comms_platform.web.app import EventBus, create_app


def test_unreal_event_start_audio_routes_to_audio_loop():
    app = create_app(
        event_bus=EventBus(),
        thread_manager=StubThreadManager(),
        signal_gateway=StubSignalGateway(),
        master_agent=StubAgentCoordinator(),
    )

    with patch(
        "comms_platform.integrations.unreal.generate_ollama_reply",
        return_value={"ok": True, "reply": "test narration", "model": "stub-model"},
    ), patch(
        "comms_platform.integrations.unreal.synthesize_tts_audio_bytes",
        return_value={"ok": True, "audio_bytes": b"RIFF", "duration": 0.1, "voice_name": "F1", "lang": "en"},
    ), __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(app) as client:
        response = client.post(
            "/api/unreal/event",
            json={
                "source": "unreal-editor",
                "event": "key_pressed",
                "message": "start audio",
                "session_id": "default",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["accepted"] is True
    assert body["routed_action"] == "start_audio"
    assert body["route_changed"] is True
    assert body["route_details"]["audio_loop_running"] is True
    assert body["agent_action"] == "none"
    assert body["agent_running"] is False

    log_test(
        "POST /api/unreal/event [start_audio]",
        f"status_code={response.status_code}, routed_action={body['routed_action']}, "
        f"audio_loop_running={body['route_details']['audio_loop_running']}",
    )

from unittest.mock import patch

from api_test_support import build_client, log_test


def test_sdxl_status_endpoint_reports_unloaded_by_default():
    with build_client() as client:
        response = client.get("/api/sdxl/status")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["engine"] == "SDXL Base 1"
    assert "loaded" in body
    log_test(
        "GET /api/sdxl/status",
        f"status_code={response.status_code}, engine={body['engine']}, loaded={body['loaded']}",
    )


def test_sdxl_engine_on_endpoint_success():
    mock_payload = {
        "ok": True,
        "engine": "SDXL Base 1",
        "loaded": True,
        "model_id": "stabilityai/stable-diffusion-xl-base-1.0",
        "device": "cpu",
    }
    with build_client() as client:
        with patch("comms_platform.web.app._set_sdxl_engine_loaded", return_value=mock_payload):
            response = client.post("/api/sdxl/engine/on")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["loaded"] is True
    log_test(
        "POST /api/sdxl/engine/on",
        f"status_code={response.status_code}, ok={body['ok']}, loaded={body['loaded']}",
    )


def test_sdxl_engine_off_endpoint_success():
    mock_payload = {
        "ok": True,
        "engine": "SDXL Base 1",
        "loaded": False,
        "model_id": "stabilityai/stable-diffusion-xl-base-1.0",
        "device": "cpu",
    }
    with build_client() as client:
        with patch("comms_platform.web.app._set_sdxl_engine_loaded", return_value=mock_payload):
            response = client.post("/api/sdxl/engine/off")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["loaded"] is False
    log_test(
        "POST /api/sdxl/engine/off",
        f"status_code={response.status_code}, ok={body['ok']}, loaded={body['loaded']}",
    )


def test_sdxl_generate_endpoint_success():
    mock_payload = {
        "ok": True,
        "engine": "SDXL Base 1",
        "loaded": True,
        "image_id": "abc123",
        "image_base64": "data:image/png;base64,ZmFrZQ==",
        "duration_seconds": 1.2,
    }
    with build_client() as client:
        with patch("comms_platform.web.app._generate_sdxl_image", return_value=mock_payload):
            response = client.post(
                "/api/sdxl/generate",
                json={
                    "prompt": "a cinematic desert city",
                    "guidance_scale": 7.0,
                    "num_inference_steps": 30,
                },
            )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["engine"] == "SDXL Base 1"
    assert body["image_id"] == "abc123"
    log_test(
        "POST /api/sdxl/generate [success]",
        f"status_code={response.status_code}, ok={body['ok']}, image_id={body['image_id']}",
    )


def test_sdxl_generate_endpoint_error():
    mock_payload = {
        "ok": False,
        "engine": "SDXL Base 1",
        "error": "pipeline_unavailable",
    }
    with build_client() as client:
        with patch("comms_platform.web.app._generate_sdxl_image", return_value=mock_payload):
            response = client.post(
                "/api/sdxl/generate",
                json={
                    "prompt": "a cinematic desert city",
                    "guidance_scale": 7.0,
                    "num_inference_steps": 30,
                },
            )

    assert response.status_code == 503
    body = response.json()
    assert body["ok"] is False
    assert "error" in body
    log_test(
        "POST /api/sdxl/generate [error]",
        f"status_code={response.status_code}, ok={body['ok']}, error={body['error']}",
    )


def test_tts_test_endpoint_requires_loaded_engine():
    with build_client() as client:
        with patch("comms_platform.web.app._get_tts_engine_loaded_state", return_value={"ok": True, "loaded": False}):
            response = client.post("/api/tts/test")

    assert response.status_code == 409
    body = response.json()
    assert body["ok"] is False
    assert body["error"] == "tts_engine_not_loaded"
    log_test(
        "POST /api/tts/test [not_loaded]",
        f"status_code={response.status_code}, ok={body['ok']}, error={body['error']}",
    )


def test_tts_test_endpoint_success():
    synth_payload = {
        "ok": True,
        "audio_bytes": b"RIFF....",
        "duration": 1.1,
        "voice_name": "F1",
        "lang": "en",
    }
    with build_client() as client:
        with patch("comms_platform.web.app._get_tts_engine_loaded_state", return_value={"ok": True, "loaded": True}):
            with patch("comms_platform.web.app._synthesize_tts_audio_bytes", return_value=synth_payload):
                response = client.post("/api/tts/test")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["engine"] == "SuperTonic 3"
    assert body["prompt"] == "hello world"
    assert "output_file" in body
    log_test(
        "POST /api/tts/test [success]",
        f"status_code={response.status_code}, ok={body['ok']}, output={body['output_file']}",
    )


def test_sdxl_test_endpoint_requires_loaded_engine():
    with build_client() as client:
        with patch("comms_platform.web.app._get_sdxl_engine_loaded_state", return_value={"ok": True, "loaded": False}):
            response = client.post("/api/sdxl/test")

    assert response.status_code == 409
    body = response.json()
    assert body["ok"] is False
    assert body["error"] == "sdxl_engine_not_loaded"
    log_test(
        "POST /api/sdxl/test [not_loaded]",
        f"status_code={response.status_code}, ok={body['ok']}, error={body['error']}",
    )


def test_sdxl_test_endpoint_success():
    gen_payload = {
        "ok": True,
        "engine": "SDXL Base 1",
        "loaded": True,
        "image_id": "test-image",
        "output_file": "output/sdxl_test.png",
    }
    with build_client() as client:
        with patch("comms_platform.web.app._get_sdxl_engine_loaded_state", return_value={"ok": True, "loaded": True}):
            with patch("comms_platform.web.app._generate_sdxl_image", return_value=gen_payload):
                response = client.post("/api/sdxl/test")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["prompt"] == "a beautiful sunny city with cars"
    assert body["image_id"] == "test-image"
    log_test(
        "POST /api/sdxl/test [success]",
        f"status_code={response.status_code}, ok={body['ok']}, image_id={body['image_id']}",
    )

from unittest.mock import patch

from api_test_support import build_client, log_test


def test_tti_status_endpoint_reports_unloaded_by_default():
    with build_client() as client:
        response = client.get("/api/tti/status")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["engine"] == "SDXL Base 1"
    assert "loaded" in body
    log_test(
        "GET /api/tti/status",
        f"status_code={response.status_code}, engine={body['engine']}, loaded={body['loaded']}",
    )


def test_tti_engine_on_endpoint_success():
    mock_payload = {
        "ok": True,
        "engine": "SDXL Base 1",
        "loaded": True,
        "model_id": "stabilityai/stable-diffusion-xl-base-1.0",
        "device": "cpu",
    }
    with build_client() as client:
        with patch("comms_platform.web.routes.inference.set_tti_engine_loaded", return_value=mock_payload):
            response = client.post("/api/tti/engine/on")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["loaded"] is True
    log_test(
        "POST /api/tti/engine/on",
        f"status_code={response.status_code}, ok={body['ok']}, loaded={body['loaded']}",
    )


def test_tti_engine_off_endpoint_success():
    mock_payload = {
        "ok": True,
        "engine": "SDXL Base 1",
        "loaded": False,
        "model_id": "stabilityai/stable-diffusion-xl-base-1.0",
        "device": "cpu",
    }
    with build_client() as client:
        with patch("comms_platform.web.routes.inference.set_tti_engine_loaded", return_value=mock_payload):
            response = client.post("/api/tti/engine/off")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["loaded"] is False
    log_test(
        "POST /api/tti/engine/off",
        f"status_code={response.status_code}, ok={body['ok']}, loaded={body['loaded']}",
    )


def test_tti_generate_endpoint_success():
    mock_payload = {
        "ok": True,
        "engine": "SDXL Base 1",
        "loaded": True,
        "image_id": "abc123",
        "image_base64": "data:image/png;base64,ZmFrZQ==",
        "duration_seconds": 1.2,
    }
    with build_client() as client:
        with patch("comms_platform.web.routes.inference.generate_tti_image", return_value=mock_payload):
            response = client.post(
                "/api/tti/generate",
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
        "POST /api/tti/generate [success]",
        f"status_code={response.status_code}, ok={body['ok']}, image_id={body['image_id']}",
    )


def test_tti_generate_endpoint_error():
    mock_payload = {
        "ok": False,
        "engine": "SDXL Base 1",
        "error": "pipeline_unavailable",
    }
    with build_client() as client:
        with patch("comms_platform.web.routes.inference.generate_tti_image", return_value=mock_payload):
            response = client.post(
                "/api/tti/generate",
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
        "POST /api/tti/generate [error]",
        f"status_code={response.status_code}, ok={body['ok']}, error={body['error']}",
    )


def test_tts_test_endpoint_requires_loaded_engine():
    with build_client() as client:
        with patch("comms_platform.web.routes.inference.get_tts_engine_loaded_state", return_value={"ok": True, "loaded": False}):
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
        with patch("comms_platform.web.routes.inference.get_tts_engine_loaded_state", return_value={"ok": True, "loaded": True}):
            with patch("comms_platform.web.routes.inference.synthesize_tts_audio_bytes", return_value=synth_payload):
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


def test_tti_test_endpoint_requires_loaded_engine():
    with build_client() as client:
        with patch("comms_platform.web.routes.inference.get_tti_engine_loaded_state", return_value={"ok": True, "loaded": False}):
            response = client.post("/api/tti/test")

    assert response.status_code == 409
    body = response.json()
    assert body["ok"] is False
    assert body["error"] == "tti_engine_not_loaded"
    log_test(
        "POST /api/tti/test [not_loaded]",
        f"status_code={response.status_code}, ok={body['ok']}, error={body['error']}",
    )


def test_tti_test_endpoint_success():
    gen_payload = {
        "ok": True,
        "engine": "SDXL Base 1",
        "loaded": True,
        "image_id": "test-image",
        "output_file": "output/tti_test.png",
    }
    with build_client() as client:
        with patch("comms_platform.web.routes.inference.get_tti_engine_loaded_state", return_value={"ok": True, "loaded": True}):
            with patch("comms_platform.web.routes.inference.generate_tti_image", return_value=gen_payload):
                response = client.post("/api/tti/test")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["prompt"] == "hello world"
    assert body["image_id"] == "test-image"
    log_test(
        "POST /api/tti/test [success]",
        f"status_code={response.status_code}, ok={body['ok']}, image_id={body['image_id']}",
    )


def test_tt3d_status_endpoint_reports_unloaded_by_default():
    with build_client() as client:
        response = client.get("/api/tt3d/status")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["engine"] == "Hunyuan3D 2.1"
    assert "loaded" in body
    log_test(
        "GET /api/tt3d/status",
        f"status_code={response.status_code}, engine={body['engine']}, loaded={body['loaded']}",
    )


def test_tt3d_engine_on_endpoint_success():
    mock_payload = {
        "ok": True,
        "engine": "Hunyuan3D 2.1",
        "loaded": True,
        "model_id": "tencent/Hunyuan3D-2.1",
        "device": "cpu",
        "texture_enabled": False,
    }
    with build_client() as client:
        with patch("comms_platform.web.routes.inference.set_tt3d_engine_loaded", return_value=mock_payload):
            response = client.post("/api/tt3d/engine/on")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["loaded"] is True
    log_test(
        "POST /api/tt3d/engine/on",
        f"status_code={response.status_code}, ok={body['ok']}, loaded={body['loaded']}",
    )


def test_tt3d_engine_off_endpoint_success():
    mock_payload = {
        "ok": True,
        "engine": "Hunyuan3D 2.1",
        "loaded": False,
        "model_id": "tencent/Hunyuan3D-2.1",
        "device": "cpu",
        "texture_enabled": False,
    }
    with build_client() as client:
        with patch("comms_platform.web.routes.inference.set_tt3d_engine_loaded", return_value=mock_payload):
            response = client.post("/api/tt3d/engine/off")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["loaded"] is False
    log_test(
        "POST /api/tt3d/engine/off",
        f"status_code={response.status_code}, ok={body['ok']}, loaded={body['loaded']}",
    )


def test_tt3d_generate_endpoint_success():
    mock_payload = {
        "ok": True,
        "engine": "Hunyuan3D 2.1",
        "loaded": True,
        "asset_id": "mesh123",
        "output_file": "output/tt3d_test.glb",
        "duration_seconds": 42.0,
    }
    with build_client() as client:
        with patch("comms_platform.web.routes.inference.generate_tt3d_asset", return_value=mock_payload):
            response = client.post(
                "/api/tt3d/generate",
                json={
                    "prompt": "a wooden chair on a white background",
                    "guidance_scale": 7.5,
                    "num_inference_steps": 30,
                },
            )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["asset_id"] == "mesh123"
    log_test(
        "POST /api/tt3d/generate [success]",
        f"status_code={response.status_code}, ok={body['ok']}, asset_id={body['asset_id']}",
    )


def test_tt3d_generate_endpoint_not_loaded():
    mock_payload = {
        "ok": False,
        "engine": "Hunyuan3D 2.1",
        "error": "tt3d_engine_not_loaded",
    }
    with build_client() as client:
        with patch("comms_platform.web.routes.inference.generate_tt3d_asset", return_value=mock_payload):
            response = client.post(
                "/api/tt3d/generate",
                json={
                    "prompt": "a wooden chair on a white background",
                    "guidance_scale": 7.5,
                    "num_inference_steps": 30,
                },
            )

    assert response.status_code == 409
    body = response.json()
    assert body["ok"] is False
    assert body["error"] == "tt3d_engine_not_loaded"
    log_test(
        "POST /api/tt3d/generate [not_loaded]",
        f"status_code={response.status_code}, ok={body['ok']}, error={body['error']}",
    )


def test_inference_prompt_endpoint_returns_state():
    with build_client() as client:
        response = client.get("/api/inference/prompt")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "prompt" in body
    assert body["engines"] == ["tts", "tti", "tt3d"]
    log_test(
        "GET /api/inference/prompt",
        f"status_code={response.status_code}, prompt_len={len(body['prompt'])}",
    )


def test_inference_prompt_post_sets_global_prompt():
    with build_client() as client:
        response = client.post(
            "/api/inference/prompt",
            json={"prompt": "a neon cyberpunk city at night"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["prompt"] == "a neon cyberpunk city at night"
    assert body["engines"] == ["tts", "tti", "tt3d"]
    log_test(
        "POST /api/inference/prompt",
        f"status_code={response.status_code}, prompt={body['prompt']}",
    )


def test_inference_prompt_post_rejects_empty_prompt():
    with build_client() as client:
        response = client.post("/api/inference/prompt", json={"prompt": "   "})

    assert response.status_code == 422 or response.status_code == 400
    log_test(
        "POST /api/inference/prompt [empty]",
        f"status_code={response.status_code}",
    )


def test_tt3d_test_endpoint_requires_loaded_engine():
    with build_client() as client:
        with patch(
            "comms_platform.web.routes.inference.get_tt3d_engine_loaded_state",
            return_value={"ok": True, "loaded": False},
        ):
            response = client.post("/api/tt3d/test")

    assert response.status_code == 409
    body = response.json()
    assert body["ok"] is False
    assert body["error"] == "tt3d_engine_not_loaded"
    log_test(
        "POST /api/tt3d/test [not_loaded]",
        f"status_code={response.status_code}, ok={body['ok']}, error={body['error']}",
    )


def test_tt3d_test_endpoint_success():
    gen_payload = {
        "ok": True,
        "engine": "Hunyuan3D 2.1",
        "loaded": True,
        "asset_id": "test-mesh",
        "output_file": "output/tt3d_test.glb",
    }
    with build_client() as client:
        with patch(
            "comms_platform.web.routes.inference.get_tt3d_engine_loaded_state",
            return_value={"ok": True, "loaded": True},
        ):
            with patch("comms_platform.web.routes.inference.generate_tt3d_asset", return_value=gen_payload):
                response = client.post("/api/tt3d/test")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["asset_id"] == "test-mesh"
    assert "prompt" in body
    log_test(
        "POST /api/tt3d/test [success]",
        f"status_code={response.status_code}, ok={body['ok']}, asset_id={body['asset_id']}",
    )

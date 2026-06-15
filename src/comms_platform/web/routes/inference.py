import asyncio
import io
from datetime import datetime, timezone

from fastapi.responses import JSONResponse, StreamingResponse

from ...constants import (
    PROJECT_ROOT,
    TTS_DEFAULT_LANG,
    TTS_DEFAULT_VOICE,
    TTI_DEFAULT_GUIDANCE,
    TTI_DEFAULT_STEPS,
    TT3D_DEFAULT_GUIDANCE,
    TT3D_DEFAULT_OCTREE_RESOLUTION,
    TT3D_DEFAULT_STEPS,
)
from ...inference.prompts import (
    get_global_inference_prompt,
    get_inference_prompt_state,
    set_global_inference_prompt,
)
from ...inference.tti import generate_tti_image, get_tti_engine_loaded_state, set_tti_engine_loaded
from ...inference.tt3d import generate_tt3d_asset, get_tt3d_engine_loaded_state, set_tt3d_engine_loaded
from ...inference.tts import (
    check_tts_engine_status,
    get_tts_engine_loaded_state,
    set_tts_engine_loaded,
    synthesize_tts_audio_bytes,
)
from ...utils.logger import get_logger
from ..context import AppContext
from ..schemas import InferencePromptPayload, Tt3dGeneratePayload, TtiGeneratePayload, TtsPayload

logger = get_logger("web.routes.inference")


def register_inference_routes(app, ctx: AppContext) -> None:
    @app.get("/api/inference/prompt")
    async def inference_prompt_get():
        return {"ok": True, **get_inference_prompt_state()}

    @app.post("/api/inference/prompt")
    async def inference_prompt_set(payload: InferencePromptPayload):
        try:
            prompt = set_global_inference_prompt(payload.prompt)
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={"ok": False, "error": "prompt_required"},
            )
        return {
            "ok": True,
            "prompt": prompt,
            "engines": ["tts", "tti", "tt3d"],
        }

    @app.post("/api/tts/synthesize")
    async def synthesize_tts(payload: TtsPayload):
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            synthesize_tts_audio_bytes,
            payload.text,
            payload.lang,
            payload.voice_name,
        )

        if not result.get("ok"):
            logger.warning("TTS synthesis failed: %s", result.get("error"))
            return JSONResponse(
                status_code=503,
                content={
                    "ok": False,
                    "error": result.get("error", "tts_synthesis_failed"),
                },
            )

        logger.info(
            "TTS synthesis completed: lang=%s voice=%s duration=%.2fs",
            result.get("lang"),
            result.get("voice_name"),
            float(result.get("duration", 0.0)),
        )

        return StreamingResponse(
            io.BytesIO(result["audio_bytes"]),
            media_type="audio/wav",
            headers={
                "X-TTS-Duration": f"{float(result.get('duration', 0.0)):.2f}",
                "X-TTS-Voice": str(result.get("voice_name", "")),
                "X-TTS-Lang": str(result.get("lang", "")),
            },
        )

    @app.post("/api/tts/test")
    async def tts_test_render():
        state = get_tts_engine_loaded_state()
        if not state.get("loaded"):
            return JSONResponse(
                status_code=409,
                content={
                    "ok": False,
                    "error": "tts_engine_not_loaded",
                    "engine": "SuperTonic 3",
                },
            )

        prompt = get_global_inference_prompt()
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            synthesize_tts_audio_bytes,
            prompt,
            TTS_DEFAULT_LANG,
            TTS_DEFAULT_VOICE,
        )
        if not result.get("ok"):
            return JSONResponse(
                status_code=503,
                content={
                    "ok": False,
                    "error": result.get("error", "tts_test_failed"),
                    "engine": "SuperTonic 3",
                },
            )

        output_dir = PROJECT_ROOT / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"tts_{ts}.wav"
        latest_path = output_dir / "tts_latest.wav"
        audio_bytes = result["audio_bytes"]
        output_path.write_bytes(audio_bytes)
        latest_path.write_bytes(audio_bytes)

        return {
            "ok": True,
            "engine": "SuperTonic 3",
            "prompt": prompt,
            "duration_seconds": float(result.get("duration", 0.0)),
            "output_file": str(output_path),
            "latest_file": str(latest_path),
        }

    @app.get("/api/tts/status")
    async def tts_status(voice_name: str = TTS_DEFAULT_VOICE):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, check_tts_engine_status, voice_name)

    @app.post("/api/tts/engine/on")
    async def tts_engine_on():
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, set_tts_engine_loaded, True)

    @app.post("/api/tts/engine/off")
    async def tts_engine_off():
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, set_tts_engine_loaded, False)

    @app.get("/api/tti/status")
    async def tti_status():
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, get_tti_engine_loaded_state)

    @app.post("/api/tti/engine/on")
    async def tti_engine_on():
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, set_tti_engine_loaded, True)
        if result.get("ok"):
            return result
        return JSONResponse(status_code=503, content=result)

    @app.post("/api/tti/engine/off")
    async def tti_engine_off():
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, set_tti_engine_loaded, False)

    @app.post("/api/tti/generate")
    async def tti_generate(payload: TtiGeneratePayload):
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            generate_tti_image,
            payload.prompt,
            payload.guidance_scale,
            payload.num_inference_steps,
            payload.seed,
        )
        if result.get("ok"):
            return result
        return JSONResponse(status_code=503, content=result)

    @app.post("/api/tti/test")
    async def tti_test_render():
        state = get_tti_engine_loaded_state()
        if not state.get("loaded"):
            return JSONResponse(
                status_code=409,
                content={
                    "ok": False,
                    "error": "tti_engine_not_loaded",
                    "engine": "SDXL Base 1",
                },
            )

        prompt = get_global_inference_prompt()
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            generate_tti_image,
            prompt,
            TTI_DEFAULT_GUIDANCE,
            TTI_DEFAULT_STEPS,
            None,
        )
        if result.get("ok"):
            result["prompt"] = prompt
            return result
        return JSONResponse(status_code=503, content=result)

    @app.get("/api/tt3d/status")
    async def tt3d_status():
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, get_tt3d_engine_loaded_state)

    @app.post("/api/tt3d/engine/on")
    async def tt3d_engine_on():
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, set_tt3d_engine_loaded, True)
        if result.get("ok"):
            return result
        return JSONResponse(status_code=503, content=result)

    @app.post("/api/tt3d/engine/off")
    async def tt3d_engine_off():
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, set_tt3d_engine_loaded, False)

    @app.post("/api/tt3d/generate")
    async def tt3d_generate(payload: Tt3dGeneratePayload):
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: generate_tt3d_asset(
                payload.prompt,
                payload.guidance_scale,
                payload.num_inference_steps,
                payload.seed,
                enable_texture=payload.enable_texture,
                octree_resolution=payload.octree_resolution,
            ),
        )
        if result.get("ok"):
            return result
        status_code = 409 if result.get("error") == "tt3d_engine_not_loaded" else 503
        return JSONResponse(status_code=status_code, content=result)

    @app.post("/api/tt3d/test")
    async def tt3d_test_render():
        state = get_tt3d_engine_loaded_state()
        if not state.get("loaded"):
            return JSONResponse(
                status_code=409,
                content={
                    "ok": False,
                    "error": "tt3d_engine_not_loaded",
                    "engine": "Hunyuan3D 2.1",
                },
            )

        prompt = get_global_inference_prompt()
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: generate_tt3d_asset(
                prompt,
                TT3D_DEFAULT_GUIDANCE,
                TT3D_DEFAULT_STEPS,
                None,
                octree_resolution=TT3D_DEFAULT_OCTREE_RESOLUTION,
            ),
        )
        if result.get("ok"):
            result["prompt"] = prompt
            return result
        return JSONResponse(status_code=503, content=result)

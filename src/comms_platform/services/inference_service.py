"""Gateway facade over in-process engines or isolated worker processes."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from ..constants import (
    TTI_DEFAULT_GUIDANCE,
    TTI_DEFAULT_STEPS,
    TTS_DEFAULT_VOICE,
    TT3D_USE_INTERNAL_TTI,
)
from ..inference.tti import (
    generate_tti_image,
    get_tti_engine_loaded_state,
    set_tti_engine_loaded,
)
from ..inference.tt3d import (
    generate_tt3d_asset,
    get_tt3d_engine_loaded_state,
    set_tt3d_engine_loaded,
)
from ..inference.tts import (
    check_tts_engine_status,
    get_tts_engine_loaded_state,
    set_tts_engine_loaded,
    synthesize_tts_audio_bytes,
)
from ..scheduler.gpu_scheduler import GpuScheduler
from ..utils.logger import get_logger
from ..workers.pool import WorkerPool

logger = get_logger("services.inference")


def _use_in_process(config: Any | None) -> bool:
    if config is not None and hasattr(config, "INFERENCE_IN_PROCESS"):
        return bool(getattr(config, "INFERENCE_IN_PROCESS"))
    return os.getenv("INFERENCE_IN_PROCESS", "false").lower() == "true"


class InferenceService:
    def __init__(self, config: Any | None = None) -> None:
        self._config = config
        self._in_process = _use_in_process(config)
        self._pool: WorkerPool | None = None
        self._scheduler: GpuScheduler | None = None
        self._gpu_lock = asyncio.Lock()

    @property
    def in_process(self) -> bool:
        return self._in_process

    @property
    def scheduler(self) -> GpuScheduler | None:
        return self._scheduler

    async def start(self) -> None:
        if self._in_process:
            logger.info("Inference service running in-process (test/local mode).")
            return

        self._pool = WorkerPool()
        await self._pool.start()
        self._scheduler = GpuScheduler(self._pool)
        logger.info("Inference service running with isolated worker processes.")

    async def stop(self) -> None:
        if self._pool is not None:
            await self._pool.stop()
            self._pool = None
            self._scheduler = None

    async def _run_in_process_gpu(self, fn) -> Any:
        async with self._gpu_lock:
            return await asyncio.to_thread(fn)

    # --- TTS ---

    async def tts_engine_on(self) -> dict[str, Any]:
        if self._in_process:
            return await asyncio.to_thread(set_tts_engine_loaded, True)
        assert self._scheduler is not None
        return await self._scheduler.run_tts("engine_on")

    async def tts_engine_off(self) -> dict[str, Any]:
        if self._in_process:
            return await asyncio.to_thread(set_tts_engine_loaded, False)
        assert self._scheduler is not None
        return await self._scheduler.run_tts("engine_off")

    async def tts_status(self, voice_name: str = TTS_DEFAULT_VOICE) -> dict[str, Any]:
        if self._in_process:
            return await asyncio.to_thread(check_tts_engine_status, voice_name)
        assert self._scheduler is not None
        return await self._scheduler.run_tts("status", {"voice_name": voice_name})

    async def tts_loaded_state(self) -> dict[str, Any]:
        if self._in_process:
            return await asyncio.to_thread(get_tts_engine_loaded_state)
        assert self._scheduler is not None
        return await self._scheduler.run_tts("loaded_state")

    async def tts_synthesize(self, text: str, lang: str, voice_name: str) -> dict[str, Any]:
        if self._in_process:
            return await asyncio.to_thread(synthesize_tts_audio_bytes, text, lang, voice_name)
        assert self._scheduler is not None
        return await self._scheduler.run_tts(
            "synthesize",
            {"text": text, "lang": lang, "voice_name": voice_name},
        )

    # --- TTI ---

    async def tti_engine_on(self) -> dict[str, Any]:
        if self._in_process:
            return await self._run_in_process_gpu(lambda: set_tti_engine_loaded(True))
        assert self._scheduler is not None
        return await self._scheduler.run_tti("engine_on")

    async def tti_engine_off(self) -> dict[str, Any]:
        if self._in_process:
            return await asyncio.to_thread(set_tti_engine_loaded, False)
        assert self._scheduler is not None
        return await self._scheduler.run_tti("engine_off")

    async def tti_status(self) -> dict[str, Any]:
        if self._in_process:
            return await asyncio.to_thread(get_tti_engine_loaded_state)
        assert self._scheduler is not None
        return await self._scheduler.run_tti("status")

    async def tti_generate(
        self,
        prompt: str,
        guidance_scale: float,
        num_inference_steps: int,
        seed: int | None,
    ) -> dict[str, Any]:
        params = {
            "prompt": prompt,
            "guidance_scale": guidance_scale,
            "num_inference_steps": num_inference_steps,
            "seed": seed,
        }
        if self._in_process:
            return await self._run_in_process_gpu(
                lambda: generate_tti_image(prompt, guidance_scale, num_inference_steps, seed)
            )
        assert self._scheduler is not None
        return await self._scheduler.run_tti("generate", params)

    # --- TT3D ---

    async def tt3d_engine_on(self) -> dict[str, Any]:
        if self._in_process:
            return await self._run_in_process_gpu(lambda: set_tt3d_engine_loaded(True))
        assert self._scheduler is not None
        return await self._scheduler.run_tt3d("engine_on")

    async def tt3d_engine_off(self) -> dict[str, Any]:
        if self._in_process:
            return await asyncio.to_thread(set_tt3d_engine_loaded, False)
        assert self._scheduler is not None
        return await self._scheduler.run_tt3d("engine_off")

    async def tt3d_status(self) -> dict[str, Any]:
        if self._in_process:
            return await asyncio.to_thread(get_tt3d_engine_loaded_state)
        assert self._scheduler is not None
        return await self._scheduler.run_tt3d("status")

    async def tt3d_generate(
        self,
        prompt: str,
        guidance_scale: float,
        num_inference_steps: int,
        seed: int | None,
        octree_resolution: int,
    ) -> dict[str, Any]:
        if self._in_process:
            async with self._gpu_lock:
                reference_file = None
                if TT3D_USE_INTERNAL_TTI:
                    tti_result = await asyncio.to_thread(
                        generate_tti_image,
                        prompt,
                        float(TTI_DEFAULT_GUIDANCE),
                        int(TTI_DEFAULT_STEPS),
                        seed,
                    )
                    if not tti_result.get("ok"):
                        return {
                            "ok": False,
                            "engine": "Hunyuan3D 2.1",
                            "error": f"tti_preflight_failed:{tti_result.get('error', 'unknown')}",
                        }
                    reference_file = tti_result.get("latest_file")

                return await asyncio.to_thread(
                    lambda: generate_tt3d_asset(
                        prompt,
                        guidance_scale,
                        num_inference_steps,
                        seed,
                        reference_file=reference_file,
                        octree_resolution=octree_resolution,
                    )
                )

        assert self._scheduler is not None
        return await self._scheduler.generate_tt3d(
            prompt=prompt,
            guidance_scale=guidance_scale,
            num_inference_steps=num_inference_steps,
            seed=seed,
            octree_resolution=octree_resolution,
        )

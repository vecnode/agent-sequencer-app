"""Serialize GPU-heavy inference across worker processes."""

from __future__ import annotations

import asyncio
from typing import Any

from ..constants import (
    TTI_DEFAULT_GUIDANCE,
    TTI_DEFAULT_STEPS,
    TT3D_USE_INTERNAL_TTI,
)
from ..utils.logger import get_logger
from ..workers.pool import WorkerPool

logger = get_logger("scheduler.gpu")


class GpuScheduler:
    """Routes TTS directly; serializes TTI and TT3D to avoid GPU OOM."""

    def __init__(self, pool: WorkerPool) -> None:
        self._pool = pool
        self._gpu_lock = asyncio.Lock()
        self._pending_gpu_jobs = 0

    @property
    def pending_gpu_jobs(self) -> int:
        return self._pending_gpu_jobs

    async def run_tts(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._pool.tts.call(method, params)

    async def run_tti(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        async with self._gpu_lock:
            self._pending_gpu_jobs += 1
            try:
                return await self._pool.tti.call(method, params)
            finally:
                self._pending_gpu_jobs -= 1

    async def run_tt3d(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        async with self._gpu_lock:
            self._pending_gpu_jobs += 1
            try:
                return await self._pool.tt3d.call(method, params)
            finally:
                self._pending_gpu_jobs -= 1

    async def generate_tt3d(
        self,
        *,
        prompt: str,
        guidance_scale: float,
        num_inference_steps: int,
        seed: int | None,
        octree_resolution: int,
        reference_file: str | None = None,
    ) -> dict[str, Any]:
        async with self._gpu_lock:
            self._pending_gpu_jobs += 1
            try:
                ref_file = reference_file
                if ref_file is None and TT3D_USE_INTERNAL_TTI:
                    tti_result = await self._pool.tti.call(
                        "generate",
                        {
                            "prompt": prompt,
                            "guidance_scale": float(TTI_DEFAULT_GUIDANCE),
                            "num_inference_steps": int(TTI_DEFAULT_STEPS),
                            "seed": seed,
                        },
                    )
                    if not tti_result.get("ok"):
                        return {
                            "ok": False,
                            "engine": "Hunyuan3D 2.1",
                            "error": f"tti_preflight_failed:{tti_result.get('error', 'unknown')}",
                        }
                    ref_file = tti_result.get("latest_file")

                return await self._pool.tt3d.call(
                    "generate",
                    {
                        "prompt": prompt,
                        "guidance_scale": guidance_scale,
                        "num_inference_steps": num_inference_steps,
                        "seed": seed,
                        "octree_resolution": octree_resolution,
                        "reference_file": ref_file,
                    },
                )
            finally:
                self._pending_gpu_jobs -= 1

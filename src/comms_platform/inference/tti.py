import base64
import io
import logging
import os
import threading
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
from PIL import Image

from ..utils.logger import get_logger

logger = get_logger("inference.tti")
warnings.filterwarnings(
    "ignore",
    message=r"`upcast_vae` is deprecated and will be removed in version 1\.0\.0\..*",
    category=FutureWarning,
)

from ..constants import PROJECT_ROOT as _PROJECT_ROOT
_TTI_MODEL_ID = os.getenv(
    "TTI_MODEL_ID",
    os.getenv("SDXL_MODEL_ID", "stabilityai/stable-diffusion-xl-base-1.0"),
)

_tti_pipeline: Any | None = None
_tti_engine_lock = threading.RLock()


def sanitize_tti_image(image_data: Any) -> Image.Image:
    """Clamp TTI output to finite RGB pixel values before saving."""
    array = np.asarray(image_data, dtype=np.float32)
    array = np.nan_to_num(array, nan=0.0, posinf=1.0, neginf=0.0)
    array = np.clip(array, 0.0, 1.0)
    if array.ndim == 2:
        array = np.stack([array, array, array], axis=-1)
    if array.ndim == 3 and array.shape[-1] > 3:
        array = array[..., :3]
    if array.ndim != 3 or array.shape[-1] != 3:
        raise ValueError(f"Unexpected TTI image shape: {array.shape}")
    return Image.fromarray((array * 255.0).round().astype(np.uint8), mode="RGB")


def get_tti_runtime() -> tuple[Any, str, Any, str | None]:
    import torch

    fallback_reason: str | None = None
    if torch.cuda.is_available():
        try:
            _ = torch.empty(1, device="cuda")
            return torch, "cuda", torch.float16, None
        except Exception as exc:
            fallback_reason = f"cuda_probe_failed: {exc}"
    else:
        fallback_reason = "torch.cuda.is_available() is false"

    return torch, "cpu", torch.float32, fallback_reason


def release_cuda_cache() -> None:
    try:
        import gc

        gc.collect()
    except Exception:
        pass

    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def get_tti_pipeline() -> Any:
    global _tti_pipeline
    with _tti_engine_lock:
        if _tti_pipeline is None:
            xformers_logger = logging.getLogger("xformers")
            previous_xformers_level = xformers_logger.level
            xformers_logger.setLevel(logging.ERROR)
            try:
                from diffusers import DiffusionPipeline

                torch, device, dtype, fallback_reason = get_tti_runtime()
                logger.info(
                    "TTI runtime probe: torch=%s torch_cuda=%s torch_version_cuda=%s",
                    getattr(torch, "__version__", "unknown"),
                    torch.cuda.is_available(),
                    getattr(getattr(torch, "version", None), "cuda", None),
                )
                logger.info("Initializing SDXL Base 1 pipeline on %s (first load may take several minutes).", device)
                if device == "cpu" and fallback_reason:
                    logger.warning("TTI CUDA not active, using CPU (%s)", fallback_reason)

                _tti_pipeline = DiffusionPipeline.from_pretrained(_TTI_MODEL_ID, torch_dtype=dtype)
                _tti_pipeline = _tti_pipeline.to(device)
                _tti_pipeline.set_progress_bar_config(disable=True)

                if device == "cuda":
                    try:
                        _tti_pipeline.enable_xformers_memory_efficient_attention()
                        logger.info("TTI xFormers attention enabled.")
                    except Exception:
                        logger.info("TTI xFormers attention unavailable; using default attention.")
                    try:
                        import torch

                        _tti_pipeline.unet.to(memory_format=torch.channels_last)
                    except Exception:
                        pass
                logger.info("SDXL Base 1 pipeline initialized on %s.", device)
            finally:
                xformers_logger.setLevel(previous_xformers_level)
        return _tti_pipeline


def set_tti_engine_loaded(loaded: bool) -> dict:
    global _tti_pipeline
    with _tti_engine_lock:
        if loaded:
            try:
                get_tti_pipeline()
                _, device, _, _ = get_tti_runtime()
                return {
                    "ok": True,
                    "engine": "SDXL Base 1",
                    "loaded": True,
                    "model_id": _TTI_MODEL_ID,
                    "device": device,
                }
            except Exception as exc:
                return {
                    "ok": False,
                    "engine": "SDXL Base 1",
                    "loaded": False,
                    "model_id": _TTI_MODEL_ID,
                    "error": str(exc),
                }

        _tti_pipeline = None
        release_cuda_cache()
        _, device, _, _ = get_tti_runtime()
        return {
            "ok": True,
            "engine": "SDXL Base 1",
            "loaded": False,
            "model_id": _TTI_MODEL_ID,
            "device": device,
        }


def get_tti_engine_loaded_state() -> dict:
    with _tti_engine_lock:
        _, device, _, _ = get_tti_runtime()
        return {
            "ok": True,
            "engine": "SDXL Base 1",
            "loaded": _tti_pipeline is not None,
            "model_id": _TTI_MODEL_ID,
            "device": device,
        }


def generate_tti_image(prompt: str, guidance_scale: float, num_inference_steps: int, seed: int | None) -> dict:
    try:
        prompt = str(prompt or "").strip()
        if not prompt:
            return {
                "ok": False,
                "error": "prompt_required",
                "engine": "SDXL Base 1",
            }

        torch, device, _, _ = get_tti_runtime()
        generator = None
        if seed is not None:
            generator = torch.Generator(device=device).manual_seed(int(seed))

        started_at = datetime.now(timezone.utc)
        pipeline = get_tti_pipeline()
        with torch.inference_mode():
            image_result = pipeline(
                prompt=prompt,
                guidance_scale=float(guidance_scale),
                num_inference_steps=int(num_inference_steps),
                generator=generator,
                output_type="np",
            ).images[0]

        image = sanitize_tti_image(image_result)
        elapsed_seconds = (datetime.now(timezone.utc) - started_at).total_seconds()

        output_dir = _PROJECT_ROOT / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"tti_{ts}.png"
        latest_path = output_dir / "tti_latest.png"
        image.save(output_path, format="PNG")
        image.save(latest_path, format="PNG")

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        image_base64 = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("utf-8")

        if device == "cuda":
            torch.cuda.empty_cache()

        return {
            "ok": True,
            "engine": "SDXL Base 1",
            "loaded": True,
            "model_id": _TTI_MODEL_ID,
            "device": device,
            "image_id": str(uuid4()),
            "image_base64": image_base64,
            "output_file": str(output_path),
            "latest_file": str(latest_path),
            "duration_seconds": elapsed_seconds,
            "guidance_scale": float(guidance_scale),
            "num_inference_steps": int(num_inference_steps),
            "seed": seed,
        }
    except Exception as exc:
        logger.warning("TTI generation failed: %s", exc)
        return {
            "ok": False,
            "engine": "SDXL Base 1",
            "error": str(exc),
        }

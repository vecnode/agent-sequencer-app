"""TT3D inference — Hunyuan3D-2.1 shape-only text-to-3D (SDXL preflight → mesh GLB)."""

from __future__ import annotations

import io
import os
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image

from ..constants import (
    PROJECT_ROOT as _PROJECT_ROOT,
    TTI_DEFAULT_GUIDANCE,
    TTI_DEFAULT_STEPS,
    TT3D_DEFAULT_GUIDANCE,
    TT3D_DEFAULT_OCTREE_RESOLUTION,
    TT3D_DEFAULT_STEPS,
    TT3D_MODEL_ID,
    TT3D_SHAPE_SUBFOLDER,
    TT3D_USE_INTERNAL_TTI,
)
from ..utils.logger import get_logger
from .tti import generate_tti_image, release_cuda_cache

logger = get_logger("inference.tt3d")

_ENGINE_NAME = "Hunyuan3D 2.1"
_HUNYUAN3D_ROOT = Path(
    os.getenv("HUNYUAN3D_ROOT", str(_PROJECT_ROOT / "vendor" / "Hunyuan3D-2.1"))
).resolve()

_shape_pipeline: Any | None = None
_rmbg_worker: Any | None = None
_tt3d_engine_lock = threading.RLock()
_hunyuan_paths_configured = False

_TT3D_PYTHON_DEPS: tuple[tuple[str, str], ...] = (
    ("einops", "einops"),
    ("timm", "timm"),
    ("torchdiffeq", "torchdiffeq"),
    ("scipy", "scipy"),
    ("cv2", "opencv-python"),
    ("trimesh", "trimesh"),
    ("rembg", "rembg"),
    ("omegaconf", "omegaconf"),
    ("pytorch_lightning", "pytorch-lightning"),
)


def _missing_tt3d_python_deps() -> list[str]:
    missing: list[str] = []
    seen: set[str] = set()
    for module_name, package_name in _TT3D_PYTHON_DEPS:
        if package_name in seen:
            continue
        seen.add(package_name)
        try:
            __import__(module_name)
        except ImportError:
            missing.append(package_name)
    return missing


def _format_missing_deps_error(missing: list[str]) -> str:
    packages = " ".join(missing)
    return (
        f"Missing TT3D Python packages: {', '.join(missing)}. "
        f"Install with: uv sync --extra tt3d "
        f"or: uv pip install {packages}"
    )


@contextmanager
def _hunyuan_workdir():
    previous = Path.cwd()
    if _HUNYUAN3D_ROOT.is_dir():
        os.chdir(_HUNYUAN3D_ROOT)
    try:
        yield
    finally:
        os.chdir(previous)


def _configure_hunyuan_paths() -> None:
    global _hunyuan_paths_configured
    if _hunyuan_paths_configured:
        return
    if not _HUNYUAN3D_ROOT.is_dir():
        raise FileNotFoundError(
            f"Hunyuan3D root not found at {_HUNYUAN3D_ROOT}. "
            "Clone https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1 and set HUNYUAN3D_ROOT."
        )
    shape_dir = _HUNYUAN3D_ROOT / "hy3dshape"
    if shape_dir.is_dir():
        path = str(shape_dir)
        if path not in sys.path:
            sys.path.insert(0, path)
    _hunyuan_paths_configured = True


def check_tt3d_prerequisites() -> dict[str, Any]:
    issues: list[str] = []
    missing_deps = _missing_tt3d_python_deps()
    if missing_deps:
        issues.append(f"missing_python_packages:{','.join(missing_deps)}")

    if not _HUNYUAN3D_ROOT.is_dir():
        issues.append(f"missing_vendor_root:{_HUNYUAN3D_ROOT}")
    else:
        shape_pipeline = _HUNYUAN3D_ROOT / "hy3dshape/hy3dshape/pipelines.py"
        if not shape_pipeline.is_file():
            issues.append(f"missing_file:{shape_pipeline.relative_to(_HUNYUAN3D_ROOT)}")

    return {
        "ok": len(issues) == 0,
        "vendor_root": str(_HUNYUAN3D_ROOT),
        "mode": "shape-only",
        "missing_python_packages": missing_deps,
        "issues": issues,
    }


def get_tt3d_runtime() -> tuple[Any, str, Any, str | None]:
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


def _get_rmbg_worker() -> Any:
    global _rmbg_worker
    with _tt3d_engine_lock:
        if _rmbg_worker is None:
            _configure_hunyuan_paths()
            try:
                from hy3dshape.rembg import BackgroundRemover

                _rmbg_worker = BackgroundRemover()
            except Exception:
                from rembg import remove as rembg_remove

                class _RembgAdapter:
                    def __call__(self, image: Image.Image) -> Image.Image:
                        output = rembg_remove(image.convert("RGB"))
                        if isinstance(output, bytes):
                            return Image.open(io.BytesIO(output)).convert("RGBA")
                        return output.convert("RGBA")

                _rmbg_worker = _RembgAdapter()
        return _rmbg_worker


def get_shape_pipeline() -> Any:
    global _shape_pipeline
    with _tt3d_engine_lock:
        if _shape_pipeline is None:
            prereq = check_tt3d_prerequisites()
            if not prereq["ok"] and any(
                issue.startswith(("missing_vendor_root", "missing_file:")) for issue in prereq["issues"]
            ):
                raise RuntimeError(
                    "Hunyuan3D prerequisites missing: " + "; ".join(prereq["issues"])
                )

            _configure_hunyuan_paths()
            from hy3dshape.pipelines import Hunyuan3DDiTFlowMatchingPipeline

            torch, device, _, fallback_reason = get_tt3d_runtime()
            logger.info("Initializing Hunyuan3D shape pipeline on %s.", device)
            if device == "cpu" and fallback_reason:
                logger.warning("TT3D CUDA not active, using CPU (%s)", fallback_reason)

            with _hunyuan_workdir():
                _shape_pipeline = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
                    TT3D_MODEL_ID,
                    subfolder=TT3D_SHAPE_SUBFOLDER,
                    use_safetensors=False,
                    device=device,
                )
            logger.info("Hunyuan3D shape pipeline initialized on %s.", device)
        return _shape_pipeline


def set_tt3d_engine_loaded(loaded: bool) -> dict:
    global _shape_pipeline, _rmbg_worker
    with _tt3d_engine_lock:
        if loaded:
            missing_deps = _missing_tt3d_python_deps()
            if missing_deps:
                return {
                    "ok": False,
                    "engine": _ENGINE_NAME,
                    "loaded": False,
                    "model_id": TT3D_MODEL_ID,
                    "error": _format_missing_deps_error(missing_deps),
                    "prerequisites": check_tt3d_prerequisites(),
                }
            try:
                get_shape_pipeline()
                _, device, _, _ = get_tt3d_runtime()
                return {
                    "ok": True,
                    "engine": _ENGINE_NAME,
                    "loaded": True,
                    "model_id": TT3D_MODEL_ID,
                    "device": device,
                    "mode": "shape-only",
                    "prerequisites": check_tt3d_prerequisites(),
                }
            except Exception as exc:
                _shape_pipeline = None
                return {
                    "ok": False,
                    "engine": _ENGINE_NAME,
                    "loaded": False,
                    "model_id": TT3D_MODEL_ID,
                    "error": str(exc),
                    "prerequisites": check_tt3d_prerequisites(),
                }

        _shape_pipeline = None
        _rmbg_worker = None
        release_cuda_cache()
        _, device, _, _ = get_tt3d_runtime()
        return {
            "ok": True,
            "engine": _ENGINE_NAME,
            "loaded": False,
            "model_id": TT3D_MODEL_ID,
            "device": device,
            "mode": "shape-only",
        }


def get_tt3d_engine_loaded_state() -> dict:
    with _tt3d_engine_lock:
        _, device, _, _ = get_tt3d_runtime()
        return {
            "ok": True,
            "engine": _ENGINE_NAME,
            "loaded": _shape_pipeline is not None,
            "model_id": TT3D_MODEL_ID,
            "device": device,
            "mode": "shape-only",
            "prerequisites": check_tt3d_prerequisites(),
        }


def _save_reference_image(image: Image.Image, output_dir: Path, ts: str) -> tuple[Path, Path]:
    ref_path = output_dir / f"tt3d_ref_{ts}.png"
    latest_ref = output_dir / "tt3d_ref_latest.png"
    image.save(ref_path, format="PNG")
    image.save(latest_ref, format="PNG")
    return ref_path, latest_ref


def _export_mesh_glb(mesh: Any, path: Path) -> None:
    mesh.export(str(path), file_type="glb")


def _maybe_reduce_faces(mesh: Any) -> Any:
    try:
        _configure_hunyuan_paths()
        from hy3dshape import FaceReducer

        return FaceReducer()(mesh)
    except Exception:
        return mesh


def _resolve_reference_image(
    prompt: str,
    seed: int | None,
    *,
    reference_file: str | None = None,
) -> tuple[Image.Image | None, str | None]:
    if reference_file:
        path = Path(reference_file)
        if not path.is_file():
            return None, f"reference_file_not_found:{path}"
        return Image.open(path).convert("RGB"), None

    if not TT3D_USE_INTERNAL_TTI:
        return None, "reference_image_required"

    tti_result = generate_tti_image(
        prompt,
        float(TTI_DEFAULT_GUIDANCE),
        int(TTI_DEFAULT_STEPS),
        seed,
    )
    if not tti_result.get("ok"):
        return None, f"tti_preflight_failed:{tti_result.get('error', 'unknown')}"

    latest_file = tti_result.get("latest_file")
    if not latest_file:
        return None, "tti_preflight_missing_output"

    return Image.open(latest_file).convert("RGB"), None


def generate_tt3d_asset(
    prompt: str,
    guidance_scale: float,
    num_inference_steps: int,
    seed: int | None,
    *,
    reference_file: str | None = None,
    octree_resolution: int = TT3D_DEFAULT_OCTREE_RESOLUTION,
) -> dict:
    try:
        prompt = str(prompt or "").strip()
        if not prompt:
            return {"ok": False, "error": "prompt_required", "engine": _ENGINE_NAME}

        if _shape_pipeline is None:
            return {"ok": False, "error": "tt3d_engine_not_loaded", "engine": _ENGINE_NAME}

        torch, device, _, _ = get_tt3d_runtime()
        generator = None
        if seed is not None:
            generator = torch.Generator(device=device).manual_seed(int(seed))

        started_at = datetime.now(timezone.utc)
        output_dir = _PROJECT_ROOT / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        reference_image, ref_error = _resolve_reference_image(
            prompt,
            seed,
            reference_file=reference_file,
        )
        if reference_image is None:
            return {"ok": False, "engine": _ENGINE_NAME, "error": ref_error or "reference_image_required"}

        _save_reference_image(reference_image, output_dir, ts)

        rmbg = _get_rmbg_worker()
        conditioned = rmbg(reference_image.convert("RGB"))
        if conditioned.mode != "RGBA":
            conditioned = conditioned.convert("RGBA")

        shape_pipeline = get_shape_pipeline()
        with torch.inference_mode():
            with _hunyuan_workdir():
                outputs = shape_pipeline(
                    image=conditioned,
                    num_inference_steps=int(num_inference_steps),
                    guidance_scale=float(guidance_scale),
                    generator=generator,
                    octree_resolution=int(octree_resolution),
                    output_type="mesh",
                )

        from hy3dshape.pipelines import export_to_trimesh

        mesh = export_to_trimesh(outputs)[0]
        mesh = _maybe_reduce_faces(mesh)

        output_path = output_dir / f"tt3d_{ts}.glb"
        latest_path = output_dir / "tt3d_latest.glb"
        _export_mesh_glb(mesh, output_path)
        latest_path.write_bytes(output_path.read_bytes())

        elapsed_seconds = (datetime.now(timezone.utc) - started_at).total_seconds()

        if device == "cuda":
            torch.cuda.empty_cache()

        return {
            "ok": True,
            "engine": _ENGINE_NAME,
            "loaded": True,
            "model_id": TT3D_MODEL_ID,
            "device": device,
            "asset_id": str(uuid4()),
            "output_file": str(output_path),
            "latest_file": str(latest_path),
            "reference_file": str(output_dir / "tt3d_ref_latest.png"),
            "duration_seconds": elapsed_seconds,
            "guidance_scale": float(guidance_scale),
            "num_inference_steps": int(num_inference_steps),
            "seed": seed,
            "mode": "shape-only",
            "octree_resolution": int(octree_resolution),
        }
    except Exception as exc:
        logger.warning("TT3D generation failed: %s", exc)
        return {"ok": False, "engine": _ENGINE_NAME, "error": str(exc)}


def prepare_tt3d_runtime() -> None:
    """Validate Hunyuan3D vendor tree at startup."""
    if not _HUNYUAN3D_ROOT.is_dir():
        logger.info("TT3D vendor not found at %s; skipping runtime preparation.", _HUNYUAN3D_ROOT)
        return
    try:
        _configure_hunyuan_paths()
        logger.info("TT3D runtime preparation complete (shape-only).")
    except Exception as exc:
        logger.warning("TT3D runtime preparation failed: %s", exc)

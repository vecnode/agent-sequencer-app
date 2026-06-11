"""TT3D inference — Hunyuan3D-2.1 text-to-3D via SDXL preflight, shape, and optional PBR paint."""

from __future__ import annotations

import io
import os
import subprocess
import sys
import threading
import tempfile
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
    TT3D_ENABLE_TEXTURE,
    TT3D_EXCLUSIVE_GPU,
    TT3D_LOW_VRAM,
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
_paint_pipeline: Any | None = None
_rmbg_worker: Any | None = None
_tt3d_engine_lock = threading.RLock()
_hunyuan_paths_configured = False
_last_texture_load_error: str | None = None

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
        f"Install with: uv pip install -e . "
        f"or: uv pip install {packages}"
    )


def _exclusive_gpu_enabled() -> bool:
    return TT3D_EXCLUSIVE_GPU


def unload_tt3d_engine_if_exclusive() -> None:
    """Unload TT3D pipelines when another GPU-heavy engine is loaded."""
    if not _exclusive_gpu_enabled():
        return
    with _tt3d_engine_lock:
        if _shape_pipeline is not None or _paint_pipeline is not None:
            set_tt3d_engine_loaded(False)


@contextmanager
def _hunyuan_workdir():
    previous = Path.cwd()
    if _HUNYUAN3D_ROOT.is_dir():
        os.chdir(_HUNYUAN3D_ROOT)
    try:
        yield
    finally:
        os.chdir(previous)


_BPY_PATCH_MARKER = "# comms-platform: optional bpy import"


def _bpy_available() -> bool:
    try:
        import bpy  # noqa: F401

        return True
    except ImportError:
        return False


def _patch_hunyuan_mesh_utils_optional_bpy() -> None:
    """Allow Hunyuan paint imports on Python versions without a bpy wheel."""
    path = _HUNYUAN3D_ROOT / "hy3dpaint" / "DifferentiableRenderer" / "mesh_utils.py"
    if not path.is_file():
        return

    text = path.read_text(encoding="utf-8")
    if _BPY_PATCH_MARKER in text:
        return
    if "import bpy" not in text:
        return

    text = text.replace(
        "import bpy",
        (
            f"{_BPY_PATCH_MARKER}\n"
            "try:\n"
            "    import bpy\n"
            "except ImportError:\n"
            "    bpy = None  # type: ignore[misc, assignment]"
        ),
        1,
    )
    convert_guard = "    if bpy is None:\n        return False\n"
    if "def convert_obj_to_glb(" in text and convert_guard not in text:
        marker = '"""Convert OBJ file to GLB format using Blender."""'
        if marker + "\n    try:" in text:
            text = text.replace(marker + "\n    try:", marker + "\n" + convert_guard + "    try:", 1)
        elif marker + "\n try:" in text:
            text = text.replace(marker + "\n try:", marker + "\n if bpy is None:\n  return False\n try:", 1)
    path.write_text(text, encoding="utf-8")
    logger.info("Applied optional-bpy patch to %s", path)


def _apply_torchvision_functional_tensor_shim() -> None:
    """Back-compat for basicsr/realesrgan on torchvision >= 0.17."""
    module_name = "torchvision.transforms.functional_tensor"
    if module_name in sys.modules:
        return
    try:
        import torchvision.transforms.functional_tensor  # noqa: F401

        return
    except ImportError:
        pass

    fix_script = _HUNYUAN3D_ROOT / "torchvision_fix.py"
    if fix_script.is_file():
        try:
            import importlib.util

            spec = importlib.util.spec_from_file_location("hunyuan_torchvision_fix", fix_script)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                if hasattr(module, "apply_fix") and module.apply_fix():
                    logger.info("Applied Hunyuan3D torchvision_fix.py shim.")
                    return
        except Exception as exc:
            logger.info("Hunyuan torchvision_fix unavailable (%s); using built-in shim.", exc)

    import types

    from torchvision.transforms import functional as functional

    shim = types.ModuleType(module_name)
    shim.rgb_to_grayscale = functional.rgb_to_grayscale
    sys.modules[module_name] = shim
    logger.info("Applied torchvision.transforms.functional_tensor compatibility shim.")


def _patch_basicsr_torchvision_import() -> None:
    """Patch installed basicsr to stop importing removed functional_tensor."""
    marker = "# comms-platform: basicsr torchvision patch"
    try:
        import basicsr
    except ImportError:
        return

    path = Path(basicsr.__file__).resolve().parent / "data" / "degradations.py"
    if not path.is_file():
        return

    text = path.read_text(encoding="utf-8")
    if marker in text:
        return

    old = "from torchvision.transforms.functional_tensor import rgb_to_grayscale"
    new = f"from torchvision.transforms.functional import rgb_to_grayscale  {marker}"
    if old not in text:
        return

    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    logger.info("Patched basicsr degradations import at %s", path)


def _apply_tt3d_compat_shims() -> None:
    _apply_torchvision_functional_tensor_shim()
    _patch_basicsr_torchvision_import()


def _find_blender_executable() -> Path | None:
    env_path = os.getenv("BLENDER_EXE", "").strip()
    if env_path:
        candidate = Path(env_path)
        if candidate.is_file():
            return candidate

    candidates = (
        Path(r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe"),
        Path(r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe"),
        Path(r"C:\Program Files\Blender Foundation\Blender 4.4\blender.exe"),
        Path(r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"),
        Path(r"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _convert_obj_to_glb_via_blender(obj_path: Path, glb_path: Path) -> bool:
    """Use a local Blender install when the bpy pip module is unavailable."""
    blender_exe = _find_blender_executable()
    if blender_exe is None:
        return False

    script = f"""
import bpy

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.obj_import(filepath=r\"{obj_path}\")
for obj in bpy.context.scene.objects:
    obj.select_set(obj.type == "MESH")
bpy.ops.export_scene.gltf(filepath=r\"{glb_path}\", export_format='GLB', use_selection=True)
"""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as handle:
        handle.write(script)
        script_path = handle.name

    try:
        result = subprocess.run(
            [str(blender_exe), "--background", "--python", script_path],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            logger.warning(
                "Blender OBJ→GLB conversion failed (code=%s): %s",
                result.returncode,
                (result.stderr or result.stdout or "").strip()[:500],
            )
            return False
        return glb_path.is_file()
    finally:
        try:
            os.remove(script_path)
        except OSError:
            pass


def _configure_hunyuan_paths() -> None:
    global _hunyuan_paths_configured
    if _hunyuan_paths_configured:
        return
    if not _HUNYUAN3D_ROOT.is_dir():
        raise FileNotFoundError(
            f"Hunyuan3D root not found at {_HUNYUAN3D_ROOT}. "
            "Clone https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1 and set HUNYUAN3D_ROOT."
        )
    _patch_hunyuan_mesh_utils_optional_bpy()
    _apply_tt3d_compat_shims()
    for subdir in ("hy3dshape", "hy3dpaint"):
        candidate = _HUNYUAN3D_ROOT / subdir
        if candidate.is_dir():
            path = str(candidate)
            if path not in sys.path:
                sys.path.insert(0, path)
    _hunyuan_paths_configured = True


_CUSTOM_RASTERIZER_HINT = (
    "Build the Hunyuan custom_rasterizer CUDA extension from the repo root: "
    ".\\scripts\\setup_hunyuan3d.ps1 "
    "(requires Visual Studio Build Tools and CUDA 12.4 to match PyTorch cu124)."
)


def _custom_rasterizer_root() -> Path:
    return _HUNYUAN3D_ROOT / "hy3dpaint" / "custom_rasterizer"


def _ensure_custom_rasterizer_path() -> None:
    _configure_hunyuan_paths()
    rasterizer_root = _custom_rasterizer_root()
    if rasterizer_root.is_dir():
        path = str(rasterizer_root)
        if path not in sys.path:
            sys.path.insert(0, path)


def _verify_custom_rasterizer() -> tuple[bool, str | None]:
    """Return whether the Hunyuan paint rasterizer CUDA extension is usable."""
    if not _HUNYUAN3D_ROOT.is_dir():
        return False, f"Hunyuan3D vendor root not found at {_HUNYUAN3D_ROOT}"
    if not _custom_rasterizer_root().is_dir():
        return False, f"custom_rasterizer sources not found at {_custom_rasterizer_root()}"

    try:
        _ensure_custom_rasterizer_path()
        with _hunyuan_workdir():
            import custom_rasterizer
            import custom_rasterizer_kernel  # noqa: F401

            if not callable(getattr(custom_rasterizer, "rasterize", None)):
                return False, (
                    "custom_rasterizer imported but rasterize() is missing; "
                    f"the CUDA kernel was not built. {_CUSTOM_RASTERIZER_HINT}"
                )
        return True, None
    except Exception as exc:
        message = str(exc)
        if "custom_rasterizer" in message:
            return False, f"{message} {_CUSTOM_RASTERIZER_HINT}"
        return False, message


def check_tt3d_prerequisites() -> dict[str, Any]:
    """Report whether the Hunyuan3D vendor tree and optional native extensions are present."""
    issues: list[str] = []
    missing_deps = _missing_tt3d_python_deps()
    if missing_deps:
        issues.append(f"missing_python_packages:{','.join(missing_deps)}")

    if not _HUNYUAN3D_ROOT.is_dir():
        issues.append(f"missing_vendor_root:{_HUNYUAN3D_ROOT}")
    else:
        for rel in (
            "hy3dshape/hy3dshape/pipelines.py",
            "hy3dpaint/textureGenPipeline.py",
        ):
            if not (_HUNYUAN3D_ROOT / rel).is_file():
                issues.append(f"missing_file:{rel}")

    texture_ready = False
    if _HUNYUAN3D_ROOT.is_dir():
        realesrgan = _HUNYUAN3D_ROOT / "hy3dpaint" / "ckpt" / "RealESRGAN_x4plus.pth"
        if not realesrgan.is_file():
            issues.append("missing_realesrgan_weights")
        try:
            texture_ready, texture_error = _verify_custom_rasterizer()
            if not texture_ready and texture_error and TT3D_ENABLE_TEXTURE:
                issues.append(f"texture_native_extensions:{texture_error}")
        except Exception as exc:
            if TT3D_ENABLE_TEXTURE:
                issues.append(f"texture_native_extensions:{exc}")

    return {
        "ok": len(issues) == 0,
        "vendor_root": str(_HUNYUAN3D_ROOT),
        "texture_ready": texture_ready,
        "texture_enabled": TT3D_ENABLE_TEXTURE,
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


def get_paint_pipeline() -> Any:
    global _paint_pipeline, _last_texture_load_error
    with _tt3d_engine_lock:
        if _paint_pipeline is None:
            if not TT3D_ENABLE_TEXTURE:
                raise RuntimeError("texture_pipeline_disabled")

            _configure_hunyuan_paths()
            _apply_tt3d_compat_shims()
            try:
                from textureGenPipeline import Hunyuan3DPaintConfig, Hunyuan3DPaintPipeline
            except Exception as exc:
                _last_texture_load_error = str(exc)
                raise

            realesrgan = _HUNYUAN3D_ROOT / "hy3dpaint" / "ckpt" / "RealESRGAN_x4plus.pth"
            if not realesrgan.is_file():
                raise FileNotFoundError(
                    f"Real-ESRGAN weights not found at {realesrgan}. "
                    "Download RealESRGAN_x4plus.pth into hy3dpaint/ckpt/."
                )

            try:
                texture_ok, texture_error = _verify_custom_rasterizer()
                if not texture_ok:
                    raise RuntimeError(texture_error or "custom_rasterizer_not_built")

                with _hunyuan_workdir():
                    conf = Hunyuan3DPaintConfig(max_num_view=8, resolution=768)
                    conf.realesrgan_ckpt_path = str(realesrgan)
                    conf.multiview_cfg_path = "hy3dpaint/cfgs/hunyuan-paint-pbr.yaml"
                    conf.custom_pipeline = "hy3dpaint/hunyuanpaintpbr"
                    _paint_pipeline = Hunyuan3DPaintPipeline(conf)
                _last_texture_load_error = None
            except Exception as exc:
                _last_texture_load_error = str(exc)
                raise
            logger.info("Hunyuan3D paint pipeline initialized.")
        return _paint_pipeline


def _tt3d_texture_active() -> bool:
    return TT3D_ENABLE_TEXTURE and _paint_pipeline is not None


def _tt3d_status_payload() -> dict[str, Any]:
    texture_requested = TT3D_ENABLE_TEXTURE
    texture_loaded = _paint_pipeline is not None
    if texture_loaded:
        mode = "shape+texture"
    elif texture_requested:
        mode = "shape-only"
    else:
        mode = "shape-only"
    payload: dict[str, Any] = {
        "texture_requested": texture_requested,
        "texture_loaded": texture_loaded,
        "texture_enabled": texture_loaded,
        "mode": mode,
    }
    if texture_requested and not texture_loaded:
        if _last_texture_load_error:
            payload["texture_warning"] = (
                f"PBR texture pipeline failed to load: {_last_texture_load_error}"
            )
        elif not _bpy_available():
            payload["texture_warning"] = (
                "Native bpy is not installed (no pip wheel for Python 3.12). "
                "The vendor patch and/or BLENDER_EXE can still provide Blender GLB export."
            )
        else:
            payload["texture_warning"] = "PBR texture pipeline failed to load; shape-only mode is active."
    payload["bpy_available"] = _bpy_available()
    payload["blender_available"] = _find_blender_executable() is not None
    return payload


def set_tt3d_engine_loaded(loaded: bool) -> dict:
    global _shape_pipeline, _paint_pipeline, _rmbg_worker, _last_texture_load_error
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
            if _exclusive_gpu_enabled():
                from .tti import set_tti_engine_loaded

                set_tti_engine_loaded(False)
            try:
                get_shape_pipeline()
                if TT3D_ENABLE_TEXTURE:
                    texture_ok, texture_error = _verify_custom_rasterizer()
                    if not texture_ok:
                        _last_texture_load_error = texture_error
                        logger.warning(
                            "TT3D texture pipeline unavailable: %s",
                            texture_error or "custom_rasterizer_not_built",
                        )
                    else:
                        try:
                            get_paint_pipeline()
                        except Exception as exc:
                            _last_texture_load_error = str(exc)
                            logger.warning("TT3D texture pipeline unavailable: %s", exc)
                _, device, _, _ = get_tt3d_runtime()
                prereq = check_tt3d_prerequisites()
                response = {
                    "ok": True,
                    "engine": _ENGINE_NAME,
                    "loaded": True,
                    "model_id": TT3D_MODEL_ID,
                    "device": device,
                    "prerequisites": prereq,
                }
                response.update(_tt3d_status_payload())
                return response
            except Exception as exc:
                _shape_pipeline = None
                _paint_pipeline = None
                return {
                    "ok": False,
                    "engine": _ENGINE_NAME,
                    "loaded": False,
                    "model_id": TT3D_MODEL_ID,
                    "error": str(exc),
                    "prerequisites": check_tt3d_prerequisites(),
                }

        _shape_pipeline = None
        _paint_pipeline = None
        _rmbg_worker = None
        release_cuda_cache()
        _, device, _, _ = get_tt3d_runtime()
        return {
            "ok": True,
            "engine": _ENGINE_NAME,
            "loaded": False,
            "model_id": TT3D_MODEL_ID,
            "device": device,
            "texture_enabled": False,
        }


def get_tt3d_engine_loaded_state() -> dict:
    with _tt3d_engine_lock:
        _, device, _, _ = get_tt3d_runtime()
        response = {
            "ok": True,
            "engine": _ENGINE_NAME,
            "loaded": _shape_pipeline is not None,
            "model_id": TT3D_MODEL_ID,
            "device": device,
            "prerequisites": check_tt3d_prerequisites(),
        }
        response.update(_tt3d_status_payload())
        return response


def _save_reference_image(image: Image.Image, output_dir: Path, ts: str) -> tuple[Path, Path]:
    ref_path = output_dir / f"tt3d_ref_{ts}.png"
    latest_ref = output_dir / "tt3d_ref_latest.png"
    image.save(ref_path, format="PNG")
    image.save(latest_ref, format="PNG")
    return ref_path, latest_ref


def _export_mesh_glb(mesh: Any, path: Path) -> None:
    mesh.export(str(path), file_type="glb")


def _convert_textured_obj_to_glb(obj_path: Path, glb_path: Path) -> None:
    if _bpy_available():
        try:
            _configure_hunyuan_paths()
            with _hunyuan_workdir():
                from DifferentiableRenderer.mesh_utils import convert_obj_to_glb

                if convert_obj_to_glb(str(obj_path), str(glb_path)):
                    return
        except Exception as exc:
            logger.info("bpy convert_obj_to_glb unavailable (%s); trying other exporters.", exc)

    if _convert_obj_to_glb_via_blender(obj_path, glb_path):
        return

    try:
        _configure_hunyuan_paths()
        with _hunyuan_workdir():
            from hy3dpaint.utils import quick_convert_with_obj2gltf

            quick_convert_with_obj2gltf(str(obj_path), str(glb_path))
            return
    except Exception as exc:
        logger.info("Hunyuan obj2gltf converter unavailable (%s); using trimesh fallback.", exc)

    import trimesh

    loaded = trimesh.load(str(obj_path), force="mesh")
    if isinstance(loaded, trimesh.Scene):
        loaded.export(str(glb_path))
    else:
        loaded.export(str(glb_path), file_type="glb")


def _maybe_reduce_faces(mesh: Any) -> Any:
    try:
        _configure_hunyuan_paths()
        from hy3dshape import FaceReducer

        return FaceReducer()(mesh)
    except Exception:
        return mesh


def generate_tt3d_asset(
    prompt: str,
    guidance_scale: float,
    num_inference_steps: int,
    seed: int | None,
    *,
    enable_texture: bool | None = None,
    octree_resolution: int = TT3D_DEFAULT_OCTREE_RESOLUTION,
) -> dict:
    global _shape_pipeline
    try:
        prompt = str(prompt or "").strip()
        if not prompt:
            return {"ok": False, "error": "prompt_required", "engine": _ENGINE_NAME}

        if _shape_pipeline is None:
            return {"ok": False, "error": "tt3d_engine_not_loaded", "engine": _ENGINE_NAME}

        texture_enabled = TT3D_ENABLE_TEXTURE if enable_texture is None else bool(enable_texture)
        texture_warning: str | None = None
        if texture_enabled and _paint_pipeline is None:
            texture_enabled = False
            texture_warning = (
                "Texture pipeline not loaded; exported shape-only GLB without PBR materials."
            )
            logger.warning("TT3D falling back to shape-only export: paint pipeline unavailable.")

        torch, device, _, _ = get_tt3d_runtime()
        generator = None
        if seed is not None:
            generator = torch.Generator(device=device).manual_seed(int(seed))

        started_at = datetime.now(timezone.utc)
        output_dir = _PROJECT_ROOT / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        reference_image: Image.Image | None = None
        if TT3D_USE_INTERNAL_TTI:
            tti_result = generate_tti_image(
                prompt,
                float(TTI_DEFAULT_GUIDANCE),
                int(TTI_DEFAULT_STEPS),
                seed,
            )
            if not tti_result.get("ok"):
                return {
                    "ok": False,
                    "engine": _ENGINE_NAME,
                    "error": f"tti_preflight_failed:{tti_result.get('error', 'unknown')}",
                }
            reference_image = Image.open(tti_result["latest_file"]).convert("RGB")
            _save_reference_image(reference_image, output_dir, ts)
            if TT3D_LOW_VRAM:
                from .tti import set_tti_engine_loaded

                set_tti_engine_loaded(False)
                release_cuda_cache()

        if reference_image is None:
            return {"ok": False, "error": "reference_image_required", "engine": _ENGINE_NAME}

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

        if texture_enabled:
            if TT3D_LOW_VRAM:
                _shape_pipeline = None
                release_cuda_cache()

            try:
                texture_ok, texture_error = _verify_custom_rasterizer()
                if not texture_ok:
                    raise RuntimeError(texture_error or "custom_rasterizer_not_built")

                with tempfile.TemporaryDirectory(prefix="tt3d_") as tmp_dir:
                    tmp_obj = Path(tmp_dir) / "mesh.obj"
                    mesh.export(str(tmp_obj), file_type="obj")
                    textured_obj = Path(tmp_dir) / "textured_mesh.obj"
                    paint_pipeline = get_paint_pipeline()
                    with _hunyuan_workdir():
                        paint_pipeline(
                            mesh_path=str(tmp_obj),
                            image_path=conditioned,
                            output_mesh_path=str(textured_obj),
                            save_glb=False,
                        )
                    _convert_textured_obj_to_glb(textured_obj, output_path)
            except Exception as paint_exc:
                logger.warning("TT3D texture pass failed (%s); exporting shape-only GLB.", paint_exc)
                texture_enabled = False
                texture_warning = (
                    f"Texture pass failed ({paint_exc}); exported shape-only GLB. "
                    f"{_CUSTOM_RASTERIZER_HINT}"
                )
                _export_mesh_glb(mesh, output_path)
        else:
            _export_mesh_glb(mesh, output_path)

        latest_path.write_bytes(output_path.read_bytes())

        elapsed_seconds = (datetime.now(timezone.utc) - started_at).total_seconds()

        if device == "cuda":
            torch.cuda.empty_cache()

        result = {
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
            "texture_enabled": texture_enabled,
            "mode": "shape+texture" if texture_enabled else "shape-only",
            "octree_resolution": int(octree_resolution),
        }
        if texture_warning:
            result["texture_warning"] = texture_warning
        return result
    except Exception as exc:
        logger.warning("TT3D generation failed: %s", exc)
        return {"ok": False, "engine": _ENGINE_NAME, "error": str(exc)}


def prepare_tt3d_runtime() -> None:
    """Apply Hunyuan3D vendor patches and torchvision/basicsr shims at startup."""
    if not _HUNYUAN3D_ROOT.is_dir():
        logger.info("TT3D vendor not found at %s; skipping runtime preparation.", _HUNYUAN3D_ROOT)
        return
    try:
        _patch_hunyuan_mesh_utils_optional_bpy()
        _apply_tt3d_compat_shims()
        logger.info("TT3D runtime preparation complete.")
    except Exception as exc:
        logger.warning("TT3D runtime preparation failed: %s", exc)

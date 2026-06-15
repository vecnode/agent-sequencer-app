import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

TTS_DEFAULT_LANG = os.getenv("TTS_DEFAULT_LANG", "en")
TTS_DEFAULT_VOICE = os.getenv("TTS_DEFAULT_VOICE", "F1")
TTS_PREWARM_ON_STARTUP = os.getenv("TTS_PREWARM_ON_STARTUP", "false").lower() == "true"
ENGINES_PRELOAD_ON_STARTUP = os.getenv("ENGINES_PRELOAD_ON_STARTUP", "true").lower() == "true"
TTI_DEFAULT_GUIDANCE = float(
    os.getenv("TTI_DEFAULT_GUIDANCE", os.getenv("SDXL_DEFAULT_GUIDANCE", "7.0"))
)
TTI_DEFAULT_STEPS = int(os.getenv("TTI_DEFAULT_STEPS", os.getenv("SDXL_DEFAULT_STEPS", "20")))
TTS_TEST_PROMPT = "hello world"
TTI_TEST_PROMPT = "a beautiful sunny city with cars"
TT3D_MODEL_ID = os.getenv("TT3D_MODEL_ID", "tencent/Hunyuan3D-2.1")
TT3D_SHAPE_SUBFOLDER = os.getenv("TT3D_SHAPE_SUBFOLDER", "hunyuan3d-dit-v2-1")
TT3D_DEFAULT_GUIDANCE = float(os.getenv("TT3D_DEFAULT_GUIDANCE", "7.5"))
TT3D_DEFAULT_STEPS = int(os.getenv("TT3D_DEFAULT_STEPS", "30"))
TT3D_DEFAULT_OCTREE_RESOLUTION = int(os.getenv("TT3D_DEFAULT_OCTREE_RESOLUTION", "256"))
TT3D_ENABLE_TEXTURE = os.getenv("TT3D_ENABLE_TEXTURE", "true").lower() == "true"
TT3D_LOW_VRAM = os.getenv("TT3D_LOW_VRAM", "true").lower() == "true"
TT3D_USE_INTERNAL_TTI = os.getenv("TT3D_USE_INTERNAL_TTI", "true").lower() == "true"
TT3D_EXCLUSIVE_GPU = os.getenv("TT3D_EXCLUSIVE_GPU", "false").lower() == "true"
TT3D_TEST_PROMPT = os.getenv(
    "TT3D_TEST_PROMPT",
    "a low-poly wooden chair, studio lighting, plain white background",
)

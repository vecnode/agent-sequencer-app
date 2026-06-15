import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

sys.path.insert(0, str(TESTS_DIR.parent / "src"))

from comms_platform.constants import TTS_TEST_PROMPT
from comms_platform.inference.prompts import set_global_inference_prompt


@pytest.fixture(autouse=True)
def reset_global_inference_prompt():
    set_global_inference_prompt(TTS_TEST_PROMPT)
    yield
    set_global_inference_prompt(TTS_TEST_PROMPT)

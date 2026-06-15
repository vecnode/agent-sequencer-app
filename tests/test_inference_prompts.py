from comms_platform.constants import TTS_TEST_PROMPT
from comms_platform.inference.prompts import (
    get_global_inference_prompt,
    get_inference_prompt_state,
    set_global_inference_prompt,
)


def test_set_global_inference_prompt_updates_state():
    set_global_inference_prompt("a neon city at night")
    assert get_global_inference_prompt() == "a neon city at night"


def test_get_inference_prompt_state_includes_defaults():
    state = get_inference_prompt_state()
    assert "prompt" in state
    assert state["engines"] == ["tts", "tti", "tt3d"]
    assert "defaults" in state


def test_set_global_inference_prompt_restores_default():
    set_global_inference_prompt(TTS_TEST_PROMPT)

from comms_platform.inference.prompts import (
    get_global_inference_prompt,
    set_global_inference_prompt,
    try_set_inference_prompt_from_text,
)
from comms_platform.constants import TTS_TEST_PROMPT


def test_try_set_inference_prompt_from_text_parses_prefix():
    result = try_set_inference_prompt_from_text("prompt: a neon city at night")
    assert result is not None
    assert result["ok"] is True
    assert result["prompt"] == "a neon city at night"
    assert get_global_inference_prompt() == "a neon city at night"


def test_try_set_inference_prompt_from_text_is_case_insensitive():
    result = try_set_inference_prompt_from_text("PROMPT: wooden chair")
    assert result is not None
    assert result["ok"] is True
    assert result["prompt"] == "wooden chair"


def test_try_set_inference_prompt_from_text_ignores_non_prompt_messages():
    assert try_set_inference_prompt_from_text("hello agent") is None


def test_try_set_inference_prompt_from_text_rejects_empty_value():
    result = try_set_inference_prompt_from_text("prompt:")
    assert result == {"ok": False, "error": "empty_prompt"}


def test_set_global_inference_prompt_restores_default():
    set_global_inference_prompt(TTS_TEST_PROMPT)

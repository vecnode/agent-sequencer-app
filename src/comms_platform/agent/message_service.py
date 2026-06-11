import asyncio
from typing import Any, Callable

from ..constants import CHAT_REPLY_MAX_CHARS, CHAT_REPLY_MAX_TOKENS
from ..inference.prompts import get_inference_prompt_state, try_set_inference_prompt_from_text
from .tool_registry import ToolRegistry
from ..integrations.ollama import generate_ollama_reply
from ..utils.logger import get_logger

logger = get_logger("master.agent.message")


async def process_agent_message(
    *,
    master_agent: Any,
    ollama_url: str,
    text: str,
    selected_model: str | None = None,
    on_model_selected: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Shared message pipeline for REST and MCP: perception routing plus optional chat reply."""
    prompt_result = try_set_inference_prompt_from_text(text)
    if prompt_result is not None:
        if not prompt_result.get("ok"):
            return {
                "ok": False,
                "reply": "Inference prompt cannot be empty. Use: prompt: your text here",
                "history_size": len(master_agent.history_text_read),
                "intent": {"route": "inference_prompt", "success": False},
                "inference_prompt": get_inference_prompt_state(),
                "ollama": {
                    "attempted": False,
                    "ok": False,
                    "model": None,
                    "error": None,
                },
            }
        return {
            "ok": True,
            "reply": f"Inference prompt set for TTS, TTI, and TT3D: {prompt_result['prompt']}",
            "history_size": len(master_agent.history_text_read),
            "intent": {"route": "inference_prompt", "success": True},
            "inference_prompt": get_inference_prompt_state(),
            "ollama": {
                "attempted": False,
                "ok": True,
                "model": None,
                "error": None,
            },
        }

    if selected_model and selected_model.strip() and on_model_selected is not None:
        on_model_selected(selected_model.strip())

    reply = master_agent.handle_human_message(text, selected_model=selected_model)
    intent = getattr(master_agent, "last_intent_decision", None)
    ollama: dict[str, Any] = {
        "attempted": False,
        "ok": False,
        "model": None,
        "error": None,
    }

    if isinstance(intent, dict) and intent.get("route") == "chat":
        if ToolRegistry.is_tools_list_request(text):
            reply = ToolRegistry.build_tools_list_reply()
            ollama = {
                "attempted": False,
                "ok": True,
                "model": None,
                "error": None,
                "source": "platform_tools",
            }
            return {
                "ok": True,
                "reply": reply,
                "history_size": len(master_agent.history_text_read),
                "intent": intent,
                "ollama": ollama,
            }

        loop = asyncio.get_running_loop()
        ollama_result = await loop.run_in_executor(
            None,
            lambda: generate_ollama_reply(
                ollama_url,
                text,
                selected_model,
                max_chars=CHAT_REPLY_MAX_CHARS,
                max_tokens=CHAT_REPLY_MAX_TOKENS,
            ),
        )
        ollama = {
            "attempted": True,
            "ok": bool(ollama_result.get("ok")),
            "model": ollama_result.get("model"),
            "error": ollama_result.get("error"),
        }
        if ollama_result.get("ok"):
            reply = str(ollama_result.get("reply", "")).strip()
            logger.info("Ollama chat reply generated using model: %s", ollama_result.get("model"))
        else:
            logger.warning("Ollama chat generation unavailable: %s", ollama_result.get("error"))

    return {
        "ok": True,
        "reply": reply,
        "history_size": len(master_agent.history_text_read),
        "intent": intent,
        "ollama": ollama,
    }

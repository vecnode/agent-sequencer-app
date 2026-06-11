import asyncio
from unittest.mock import MagicMock

from comms_platform.agent.message_service import process_agent_message


class StubIntentAgent:
    def __init__(self, intent: dict):
        self._intent = intent
        self._history: list[str] = []

    @property
    def history_text_read(self):
        return list(self._history)

    @property
    def last_intent_decision(self):
        return self._intent

    def handle_human_message(self, text: str, selected_model: str | None = None):
        self._history.append(text.strip())
        return "placeholder"


def test_tools_question_returns_platform_tool_list():
    agent = StubIntentAgent(
        {
            "intent": "chat",
            "route": "chat",
            "confidence": 0.95,
            "tool_name": None,
            "reason": "default_chat_route",
        }
    )

    result = asyncio.run(
        process_agent_message(
            master_agent=agent,
            ollama_url="http://127.0.0.1:11434",
            text="Can you tell me your tools?",
        )
    )

    assert result["ok"] is True
    assert "agent_start" in result["reply"]
    assert "agent_stop" in result["reply"]
    assert result["ollama"]["source"] == "platform_tools"
    assert result["ollama"]["attempted"] is False


def test_prompt_directive_sets_global_inference_prompt():
    agent = StubIntentAgent(
        {
            "intent": "chat",
            "route": "chat",
            "confidence": 0.95,
            "tool_name": None,
            "reason": "default_chat_route",
        }
    )

    result = asyncio.run(
        process_agent_message(
            master_agent=agent,
            ollama_url="http://127.0.0.1:11434",
            text="prompt: a glowing crystal orb",
        )
    )

    assert result["ok"] is True
    assert "a glowing crystal orb" in result["reply"]
    assert result["intent"]["route"] == "inference_prompt"
    assert result["inference_prompt"]["prompt"] == "a glowing crystal orb"
    assert agent.history_text_read == []


def test_chat_route_still_calls_ollama_for_normal_questions():
    agent = StubIntentAgent(
        {
            "intent": "chat",
            "route": "chat",
            "confidence": 0.95,
            "tool_name": None,
            "reason": "default_chat_route",
        }
    )

    with MagicMock() as mock_generate:
        mock_generate.return_value = {
            "ok": True,
            "model": "gemma3:4b",
            "error": None,
            "reply": "Short reply.",
        }
        import comms_platform.agent.message_service as message_service

        original = message_service.generate_ollama_reply
        message_service.generate_ollama_reply = mock_generate
        try:
            result = asyncio.run(
                process_agent_message(
                    master_agent=agent,
                    ollama_url="http://127.0.0.1:11434",
                    text="Hello are you well?",
                )
            )
        finally:
            message_service.generate_ollama_reply = original

    assert result["reply"] == "Short reply."
    assert result["ollama"]["attempted"] is True

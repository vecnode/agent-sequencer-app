from unittest.mock import MagicMock, patch

from comms_platform.agent.perception_engine import (
    IntentClassification,
    PerceptionEngine,
)


def _build_engine(**kwargs) -> PerceptionEngine:
    defaults = {
        "ollama_base_url": "http://127.0.0.1:11434",
        "model_name": "llama3.2:latest",
        "enabled": True,
    }
    defaults.update(kwargs)
    with patch.object(PerceptionEngine, "_try_connect_model", return_value=None):
        return PerceptionEngine(**defaults)


def test_classify_empty_input_defaults_to_chat():
    engine = _build_engine()
    decision = engine.classify("   ")
    assert decision.intent == "chat"
    assert decision.route == "chat"
    assert decision.reason == "empty_input_fallback"


def test_classify_tool_intent_routes_to_tool():
    engine = _build_engine()
    mock_client = MagicMock()
    mock_client.create.return_value = IntentClassification(
        intent="tool",
        confidence=0.95,
        tool_name="agent_start",
    )

    with patch.object(engine, "_build_instructor_client", return_value=mock_client):
        decision = engine.classify("please start the agent")

    assert decision.intent == "tool"
    assert decision.route == "tool"
    assert decision.tool_name == "agent_start"
    assert decision.reason == "tool_confident"


def test_classify_low_confidence_falls_back_to_chat():
    engine = _build_engine(uncertain_threshold=0.6)
    mock_client = MagicMock()
    mock_client.create.return_value = IntentClassification(
        intent="tool",
        confidence=0.4,
        tool_name="agent_stop",
    )

    with patch.object(engine, "_build_instructor_client", return_value=mock_client):
        decision = engine.classify("maybe stop agent")

    assert decision.route == "chat"
    assert decision.reason == "low_confidence"


def test_classify_missing_tool_name_infers_start_from_text():
    engine = _build_engine()
    mock_client = MagicMock()
    mock_client.create.return_value = IntentClassification.model_construct(
        intent="tool",
        confidence=0.9,
        tool_name=None,
    )

    with patch.object(engine, "_build_instructor_client", return_value=mock_client):
        decision = engine.classify("Turn the agent ON")

    assert decision.route == "tool"
    assert decision.tool_name == "agent_start"
    assert decision.reason == "tool_confident"


def test_classify_missing_tool_name_fails_tool_parse():
    engine = _build_engine()
    mock_client = MagicMock()
    mock_client.create.return_value = IntentClassification.model_construct(
        intent="tool",
        confidence=0.9,
        tool_name=None,
    )

    with patch.object(engine, "_build_instructor_client", return_value=mock_client):
        decision = engine.classify("do something")

    assert decision.route == "chat"
    assert decision.reason == "tool_parse_failed"


def test_resolve_model_name_uses_ollama_client_list():
    engine = _build_engine(model_name=None)
    mock_list = MagicMock()
    mock_list.models = [MagicMock(model="mistral:latest")]
    engine._ollama_client = MagicMock()
    engine._ollama_client.list.return_value = mock_list

    assert engine._resolve_model_name(None) == "mistral:latest"


def test_build_instructor_client_uses_local_ollama_transport_without_retries():
    engine = _build_engine(model_name="gemma3:4b")

    with patch("comms_platform.agent.perception_engine.OpenAI") as mock_openai, patch(
        "comms_platform.agent.perception_engine.instructor.from_openai",
        return_value=MagicMock(),
    ) as mock_from_openai:
        engine._build_instructor_client("gemma3:4b")

    mock_openai.assert_called_once_with(
        base_url="http://127.0.0.1:11434/v1",
        api_key="ollama",
        max_retries=0,
    )
    mock_from_openai.assert_called_once()
    assert mock_from_openai.call_args.kwargs["mode"].name == "JSON_SCHEMA"

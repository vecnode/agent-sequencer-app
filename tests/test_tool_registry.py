from comms_platform.agent.tool_registry import ToolRegistry


class StubAgent:
    def __init__(self):
        self._running = False

    @property
    def is_running(self):
        return self._running

    def start(self):
        if self._running:
            return False
        self._running = True
        return True

    def stop(self):
        if not self._running:
            return False
        self._running = False
        return True


def test_perception_tool_names_match_agent_tools():
    names = ToolRegistry.perception_tool_names()
    assert names == frozenset({"agent_start", "agent_stop"})


def test_build_perception_tools_prompt_lists_tools():
    prompt = ToolRegistry.build_perception_tools_prompt()
    assert "agent_start" in prompt
    assert "agent_stop" in prompt


def test_execute_agent_start_and_stop():
    agent = StubAgent()
    registry = ToolRegistry(agent)

    start = registry.execute("agent_start")
    assert start.ok is True
    assert start.data["running"] is True

    stop = registry.execute("agent_stop")
    assert stop.ok is True
    assert stop.data["running"] is False


def test_execute_unknown_tool():
    agent = StubAgent()
    registry = ToolRegistry(agent)
    result = registry.execute("unknown_tool")
    assert result.ok is False


def test_infer_tool_name_turn_agent_on():
    assert ToolRegistry.infer_tool_name_from_text("Turn the agent ON") == "agent_start"


def test_infer_tool_name_turn_agent_off():
    assert ToolRegistry.infer_tool_name_from_text("Please turn the agent off") == "agent_stop"


def test_is_tools_list_request():
    assert ToolRegistry.is_tools_list_request("Can you tell me your tools?") is True
    assert ToolRegistry.is_tools_list_request("Hello are you well?") is False


def test_build_tools_list_reply_lists_platform_tools():
    reply = ToolRegistry.build_tools_list_reply()
    assert "agent_start" in reply
    assert "agent_stop" in reply
    assert "Platform tools:" in reply

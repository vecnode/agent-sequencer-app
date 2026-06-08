from dataclasses import dataclass
from typing import Any, Protocol


class MasterAgentLike(Protocol):
    def start(self) -> bool: ...

    def stop(self, timeout: float = 2.0) -> bool: ...

    @property
    def is_running(self) -> bool: ...


@dataclass(frozen=True)
class PlatformToolSpec:
    name: str
    description: str
    examples: tuple[str, ...] = ()


@dataclass
class ToolResult:
    ok: bool
    tool: str
    message: str
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "tool": self.tool,
            "message": self.message,
            **self.data,
        }


class ToolRegistry:
    """Single source of truth for platform tools used by perception, REST, and MCP."""

    AGENT_TOOLS: tuple[PlatformToolSpec, ...] = (
        PlatformToolSpec(
            name="agent_start",
            description="Start or run the master agent heartbeat loop.",
            examples=("start agent", "turn the agent on", "turn agent on", "run example"),
        ),
        PlatformToolSpec(
            name="agent_stop",
            description="Stop the master agent heartbeat loop.",
            examples=("stop agent", "turn the agent off", "turn agent off", "halt agent"),
        ),
    )

    def __init__(self, master_agent: MasterAgentLike) -> None:
        self._master_agent = master_agent

    @classmethod
    def perception_tool_names(cls) -> frozenset[str]:
        return frozenset(tool.name for tool in cls.AGENT_TOOLS)

    START_PHRASES: tuple[str, ...] = (
        "agent start",
        "start agent",
        "start the agent",
        "turn agent on",
        "turn the agent on",
        "turn on agent",
        "turn on the agent",
        "run agent",
        "run the agent",
        "run example",
        "activate agent",
    )
    STOP_PHRASES: tuple[str, ...] = (
        "agent stop",
        "stop agent",
        "stop the agent",
        "turn agent off",
        "turn the agent off",
        "turn off agent",
        "turn off the agent",
        "halt agent",
        "shutdown agent",
        "deactivate agent",
    )

    TOOLS_LIST_MARKERS: tuple[str, ...] = (
        "tell me your tools",
        "what are your tools",
        "what tools",
        "list tools",
        "your tools",
        "available tools",
        "platform tools",
        "which tools",
        "tools do you have",
    )

    @classmethod
    def is_tools_list_request(cls, text: str) -> bool:
        lowered = " ".join(text.lower().split())
        return any(marker in lowered for marker in cls.TOOLS_LIST_MARKERS)

    @classmethod
    def build_tools_list_reply(cls) -> str:
        lines = ["Platform tools:"]
        for tool in cls.AGENT_TOOLS:
            examples = ", ".join(f'"{example}"' for example in tool.examples)
            lines.append(f"- {tool.name}: {tool.description}")
            if examples:
                lines.append(f"  Say: {examples}")
        lines.append('Example: "Turn the agent ON" or "Turn the agent OFF".')
        return "\n".join(lines)

    @classmethod
    def infer_tool_name_from_text(cls, text: str) -> str | None:
        """Keyword fallback when the LLM selects tool intent without tool_name."""
        lowered = " ".join(text.lower().split())
        for phrase in cls.STOP_PHRASES:
            if phrase in lowered:
                return "agent_stop"
        for phrase in cls.START_PHRASES:
            if phrase in lowered:
                return "agent_start"
        return None

    @classmethod
    def build_perception_tools_prompt(cls) -> str:
        lines = ["Available tools (set tool_name only when intent is tool):"]
        for tool in cls.AGENT_TOOLS:
            example_text = ", ".join(f'"{example}"' for example in tool.examples)
            suffix = f" (e.g. {example_text})" if example_text else ""
            lines.append(f"- {tool.name}: {tool.description}{suffix}")
        return "\n".join(lines)

    def execute(self, tool_name: str) -> ToolResult:
        if tool_name == "agent_start":
            started = self._master_agent.start()
            running = self._master_agent.is_running
            return ToolResult(
                ok=True,
                tool=tool_name,
                message="Master agent started." if started else "Master agent already running.",
                data={"started": started, "running": running},
            )

        if tool_name == "agent_stop":
            stopped = self._master_agent.stop()
            running = self._master_agent.is_running
            return ToolResult(
                ok=True,
                tool=tool_name,
                message="Master agent stopped." if stopped else "Master agent was not running.",
                data={"stopped": stopped, "running": running},
            )

        return ToolResult(
            ok=False,
            tool=tool_name,
            message=f"Unknown tool: {tool_name}",
            data={"running": self._master_agent.is_running},
        )

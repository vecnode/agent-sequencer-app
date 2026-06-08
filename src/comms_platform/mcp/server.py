import json
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from ..agent.message_service import process_agent_message
from ..agent.tool_registry import ToolRegistry
from ..utils.logger import get_logger
from ..web.context import AppContext

logger = get_logger("mcp.server")

MCP_INSTRUCTIONS = """\
Communications platform control plane for the master agent and runtime state.

Use agent_message for natural-language requests. Perception (Instructor + local Ollama) \
classifies intent and may start/stop the agent or return a chat reply.

Use agent_start and agent_stop for direct lifecycle control without classification.

Read platform://agent/state and platform://agent/intent for live runtime snapshots.\
"""


def build_agent_state(ctx: AppContext) -> dict[str, Any]:
    return {
        "running": ctx.master_agent.is_running,
        "heartbeat_count": ctx.master_agent.heartbeat_count,
        "history_size": len(ctx.master_agent.history_text_read),
        "last_intent": ctx.master_agent.last_intent_decision,
        "sse_clients": ctx.event_bus.subscriber_count,
        "selected_model": ctx.selected_model,
    }


def create_platform_mcp(ctx: AppContext) -> FastMCP:
    registry = ToolRegistry(ctx.master_agent)

    web_host = getattr(ctx.config, "WEB_HOST", "127.0.0.1") if ctx.config is not None else "127.0.0.1"
    web_port = getattr(ctx.config, "WEB_PORT", 8000) if ctx.config is not None else 8000

    mcp = FastMCP(
        name="communications-platform",
        instructions=MCP_INSTRUCTIONS,
        host=web_host,
        port=web_port,
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
            allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"],
        ),
    )

    @mcp.tool()
    async def agent_start() -> dict[str, Any]:
        """Start the master agent heartbeat loop."""
        result = registry.execute("agent_start")
        logger.info("MCP agent_start: running=%s", result.data.get("running"))
        return result.to_dict()

    @mcp.tool()
    async def agent_stop() -> dict[str, Any]:
        """Stop the master agent heartbeat loop."""
        result = registry.execute("agent_stop")
        logger.info("MCP agent_stop: running=%s", result.data.get("running"))
        return result.to_dict()

    @mcp.tool()
    async def agent_status() -> dict[str, Any]:
        """Return current master agent runtime status."""
        return build_agent_state(ctx)

    @mcp.tool()
    async def agent_message(text: str, selected_model: str | None = None) -> dict[str, Any]:
        """Send natural-language input through perception routing and optional Ollama chat."""
        clean_text = text.strip()
        if not clean_text:
            return {
                "ok": False,
                "error": "empty_message",
                "reply": "Message text is required.",
            }

        payload = await process_agent_message(
            master_agent=ctx.master_agent,
            ollama_url=ctx.ollama_url,
            text=clean_text,
            selected_model=selected_model,
            on_model_selected=lambda model: setattr(ctx, "selected_model", model),
        )
        logger.info(
            "MCP agent_message: route=%s reply_len=%d",
            (payload.get("intent") or {}).get("route"),
            len(str(payload.get("reply", ""))),
        )
        return payload

    @mcp.resource("platform://agent/state")
    def agent_state_resource() -> str:
        """JSON snapshot of master agent and connection runtime state."""
        return json.dumps(build_agent_state(ctx), indent=2)

    @mcp.resource("platform://agent/intent")
    def agent_intent_resource() -> str:
        """JSON snapshot of the most recent perception routing decision."""
        intent = ctx.master_agent.last_intent_decision
        return json.dumps(intent or {}, indent=2)

    return mcp

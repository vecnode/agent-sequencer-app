import asyncio
import json
from contextlib import asynccontextmanager

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from api_test_support import StubAgentCoordinator, StubSignalGateway, StubThreadManager
from comms_platform.transport.event_bus import EventBus
from comms_platform.web.app import create_app


def _build_app(agent: StubAgentCoordinator | None = None):
    return create_app(
        event_bus=EventBus(),
        thread_manager=StubThreadManager(),
        signal_gateway=StubSignalGateway(),
        master_agent=agent or StubAgentCoordinator(),
    )


@asynccontextmanager
async def _mcp_test_client(app):
    mcp_server = app.state.mcp_server
    mount_path = app.state.mcp_mount_path
    mcp_url = f"http://127.0.0.1:8000{mount_path.rstrip('/')}/"

    async with mcp_server.session_manager.run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:8000",
        ) as http_client:
            async with streamable_http_client(mcp_url, http_client=http_client) as (read, write, _get_session_id):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session


def test_mcp_mount_enabled_on_app():
    app = _build_app()
    assert hasattr(app.state, "mcp_mount_path")
    assert app.state.mcp_mount_path == "/mcp"
    assert hasattr(app.state, "mcp_server")


async def _list_mcp_tools(app):
    async with _mcp_test_client(app) as session:
        tools = await session.list_tools()
        return {tool.name for tool in tools.tools}


def test_mcp_lists_platform_tools():
    app = _build_app()
    tool_names = asyncio.run(_list_mcp_tools(app))
    assert tool_names == {"agent_start", "agent_stop", "agent_status", "agent_message"}


async def _call_start_stop(app):
    async with _mcp_test_client(app) as session:
        start_result = await session.call_tool("agent_start", {})
        start_payload = json.loads(start_result.content[0].text)

        stop_result = await session.call_tool("agent_stop", {})
        stop_payload = json.loads(stop_result.content[0].text)
        return start_payload, stop_payload


def test_mcp_agent_start_stop_tools():
    agent = StubAgentCoordinator()
    app = _build_app(agent)
    start_payload, stop_payload = asyncio.run(_call_start_stop(app))
    assert start_payload["running"] is True
    assert stop_payload["running"] is False

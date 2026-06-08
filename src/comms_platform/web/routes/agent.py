from ...agent.message_service import process_agent_message
from ...utils.logger import get_logger
from ..context import AppContext
from ..schemas import AgentMessagePayload

logger = get_logger("web.routes.agent")


def register_agent_routes(app, ctx: AppContext) -> None:
    @app.post("/api/agent/start")
    async def start_agent():
        started = ctx.master_agent.start()
        return {
            "ok": True,
            "started": started,
            "running": ctx.master_agent.is_running,
        }

    @app.post("/api/agent/stop")
    async def stop_agent():
        stopped = ctx.master_agent.stop()
        return {
            "ok": True,
            "stopped": stopped,
            "running": ctx.master_agent.is_running,
        }

    @app.post("/api/agent/message")
    async def send_agent_message(payload: AgentMessagePayload):
        return await process_agent_message(
            master_agent=ctx.master_agent,
            ollama_url=ctx.ollama_url,
            text=payload.text,
            selected_model=payload.selected_model,
            on_model_selected=lambda model: setattr(ctx, "selected_model", model),
        )

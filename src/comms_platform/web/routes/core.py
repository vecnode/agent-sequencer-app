import asyncio
import json

from fastapi.responses import HTMLResponse, StreamingResponse

from ..constants import STATIC_DIR
from ..context import AppContext


def register_core_routes(app, ctx: AppContext) -> None:
    @app.get("/", response_class=HTMLResponse)
    async def index():
        return HTMLResponse(content=(STATIC_DIR / "index.html").read_text(encoding="utf-8"))

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "communications-platform"}

    @app.get("/api/status")
    async def api_status():
        return {
            "status": "running",
            "sse_clients": ctx.event_bus.subscriber_count,
            "osc_output": f"{ctx.signal_gateway.osc_output_host}:{ctx.signal_gateway.osc_output_port}",
            "osc_input": f"{ctx.signal_gateway.osc_input_host}:{ctx.signal_gateway.osc_input_port}",
            "agent_running": ctx.master_agent.is_running,
            "agent_heartbeats": ctx.master_agent.heartbeat_count,
        }

    @app.get("/events")
    async def sse_events():
        async def stream():
            q = ctx.event_bus.subscribe()
            try:
                while True:
                    data = await q.get()
                    yield f"data: {json.dumps(data)}\n\n"
            except asyncio.CancelledError:
                pass
            finally:
                ctx.event_bus.unsubscribe(q)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

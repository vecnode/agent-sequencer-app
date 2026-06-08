import asyncio
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import Body
from fastapi.responses import JSONResponse

from ...constants import EXAMPLE_TOE_PATH
from ...integrations.ollama import fetch_ollama_status, open_ollama_application
from ...integrations.touchdesigner import list_touchdesigner_processes, post_to_td_webserver
from ...integrations.unreal import UnrealOrchestrator
from ...utils.logger import get_logger
from ..context import AppContext
from ..schemas import SendToUnrealPayload, TdWebPayload, UnrealEventPayload

logger = get_logger("web.routes.third_party")


def register_third_party_routes(app, ctx: AppContext, unreal: UnrealOrchestrator) -> None:
    @app.post("/api/unreal/event")
    async def ingest_unreal_event(payload: UnrealEventPayload):
        request_id = str(uuid4())
        route_result = await unreal.route_command(payload, request_id)

        agent_action = route_result["action"] if route_result["action"].startswith("agent_") else "none"
        agent_changed = route_result["changed"] if agent_action != "none" else False
        agent_running = ctx.master_agent.is_running

        logger.info(
            "Unreal event [%s] source=%s event=%s session_id=%s",
            request_id,
            payload.source,
            payload.event,
            payload.session_id or "none",
        )
        logger.info(
            "Unreal event routed [%s]: action=%s changed=%s running=%s",
            request_id,
            route_result["action"],
            route_result["changed"],
            agent_running,
        )

        ctx.event_bus.publish(
            {
                "kind": "unreal_event",
                "address": f"/unreal/{payload.event}",
                "params": [payload.message] if payload.message else [],
                "protocol": "unreal",
                "direction": "inbound",
                "source": payload.source,
                "request_id": request_id,
                "event": payload.event,
                "message": payload.message,
                "timestamp_utc": payload.timestamp_utc,
                "session_id": payload.session_id,
                "metadata": payload.metadata,
            }
        )

        return {
            "ok": True,
            "accepted": True,
            "request_id": request_id,
            "source": payload.source,
            "event": payload.event,
            "agent_action": agent_action,
            "agent_changed": agent_changed,
            "agent_running": agent_running,
            "routed_action": route_result["action"],
            "route_changed": route_result["changed"],
            "route_details": route_result["details"],
        }

    @app.post("/api/platform/send-to-unreal")
    async def send_to_unreal(payload: SendToUnrealPayload):
        url = f"http://{payload.unreal_host}:{payload.unreal_port}/notify"
        body = {"message": payload.message}
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(url, json=body)
            resp.raise_for_status()
            logger.info("Sent to Unreal /notify: %r -> %d", payload.message, resp.status_code)
            return {"ok": True, "message": payload.message, "unreal_status": resp.status_code}
        except httpx.ConnectError:
            logger.warning("Unreal not reachable at %s", url)
            return JSONResponse(status_code=503, content={"ok": False, "error": "Unreal not reachable", "url": url})
        except httpx.HTTPStatusError as exc:
            logger.warning("Unreal /notify returned %d", exc.response.status_code)
            return JSONResponse(
                status_code=502,
                content={"ok": False, "error": f"Unreal returned {exc.response.status_code}"},
            )
        except Exception as exc:
            logger.exception("Unexpected error sending to Unreal")
            return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})

    @app.post("/api/touchdesigner/run-example")
    async def run_touchdesigner_example():
        toe_path = EXAMPLE_TOE_PATH.resolve()
        if not toe_path.exists():
            return {
                "ok": False,
                "error": "TouchDesigner file not found.",
                "path": str(toe_path),
            }

        try:
            if hasattr(os, "startfile"):
                os.startfile(str(toe_path))  # type: ignore[attr-defined]
            elif os.name == "posix":
                opener = "open" if Path("/usr/bin/open").exists() else "xdg-open"
                subprocess.Popen([opener, str(toe_path)])
            else:
                raise RuntimeError("Unsupported operating system for launching .toe files")
        except Exception as exc:
            logger.exception("Failed to launch TouchDesigner file: %s", toe_path)
            return {
                "ok": False,
                "error": str(exc),
                "path": str(toe_path),
            }

        return {
            "ok": True,
            "path": str(toe_path),
        }

    @app.post("/api/touchdesigner/send-test-data")
    async def send_touchdesigner_test_data(body: TdWebPayload = Body(default=None)):
        if body is None:
            body = TdWebPayload()
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            post_to_td_webserver,
            ctx.td_web_url,
            body.payload,
            body.timeout,
        )
        logger.info(
            "TD webserver POST [%s] → %s",
            ctx.td_web_url,
            "ok" if result["ok"] else f"error: {result.get('error')}",
        )
        return result

    @app.get("/api/touchdesigner/processes")
    async def touchdesigner_processes():
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, list_touchdesigner_processes)

    @app.get("/api/ollama/status")
    async def get_ollama_status():
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, fetch_ollama_status, ctx.ollama_url)

    @app.post("/api/ollama/open")
    async def open_ollama():
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, open_ollama_application)
        if result.get("ok"):
            return result
        return JSONResponse(status_code=503, content=result)

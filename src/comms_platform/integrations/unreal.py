import asyncio
from datetime import datetime, timezone
from pathlib import Path

from ..inference.tti import generate_tti_image
from ..inference.tts import synthesize_tts_audio_bytes
from ..constants import (
    PROJECT_ROOT,
    TTI_DEFAULT_GUIDANCE,
    TTI_DEFAULT_STEPS,
    UNREAL_AUDIO_INTERVAL_SECONDS,
    UNREAL_AUDIO_PROMPT,
    UNREAL_IMAGE_PROMPT,
)
from ..utils.logger import get_logger
from ..web.context import AppContext
from ..web.schemas import UnrealEventPayload
from .ollama import generate_ollama_reply

logger = get_logger("integrations.unreal")


def normalize_unreal_command(message: str) -> str:
    return " ".join(str(message or "").strip().lower().split())


class UnrealOrchestrator:
    """Routes Unreal events and runs background audio/image generation loops."""

    def __init__(self, ctx: AppContext) -> None:
        self._ctx = ctx

    async def execute_image_generation(self, trigger: str) -> dict:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            generate_tti_image,
            UNREAL_IMAGE_PROMPT,
            TTI_DEFAULT_GUIDANCE,
            TTI_DEFAULT_STEPS,
            None,
        )
        if result.get("ok"):
            logger.info(
                "Unreal image generation completed (trigger=%s): file=%s",
                trigger,
                result.get("output_file"),
            )
            self._ctx.event_bus.publish(
                {
                    "kind": "stream",
                    "address": "/unreal/start_image",
                    "params": [result.get("output_file", ""), UNREAL_IMAGE_PROMPT],
                    "source": "platform",
                    "protocol": "internal",
                    "direction": "outbound",
                }
            )
        else:
            logger.warning(
                "Unreal image generation failed (trigger=%s): %s",
                trigger,
                result.get("error"),
            )
        return result

    async def run_audio_loop(self, trigger: str) -> None:
        try:
            loop = asyncio.get_running_loop()
            while True:
                ollama_result = await loop.run_in_executor(
                    None,
                    generate_ollama_reply,
                    self._ctx.ollama_url,
                    UNREAL_AUDIO_PROMPT,
                    self._ctx.selected_model,
                )
                if not ollama_result.get("ok"):
                    logger.warning(
                        "Unreal audio loop Ollama step failed (trigger=%s): %s",
                        trigger,
                        ollama_result.get("error"),
                    )
                    await asyncio.sleep(UNREAL_AUDIO_INTERVAL_SECONDS)
                    continue

                reply_text = str(ollama_result.get("reply", "")).strip()
                if not reply_text:
                    logger.warning("Unreal audio loop produced empty text (trigger=%s).", trigger)
                    await asyncio.sleep(UNREAL_AUDIO_INTERVAL_SECONDS)
                    continue

                tts_result = await loop.run_in_executor(
                    None,
                    synthesize_tts_audio_bytes,
                    reply_text,
                    self._ctx.tts_default_lang,
                    self._ctx.tts_default_voice,
                )
                if not tts_result.get("ok"):
                    logger.warning(
                        "Unreal audio loop TTS step failed (trigger=%s): %s",
                        trigger,
                        tts_result.get("error"),
                    )
                    await asyncio.sleep(UNREAL_AUDIO_INTERVAL_SECONDS)
                    continue

                output_dir = PROJECT_ROOT / "output"
                output_dir.mkdir(parents=True, exist_ok=True)
                ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                output_path = output_dir / f"unreal_audio_{ts}.wav"
                latest_path = output_dir / "unreal_audio_latest.wav"
                audio_bytes = tts_result["audio_bytes"]
                output_path.write_bytes(audio_bytes)
                latest_path.write_bytes(audio_bytes)

                self._ctx.event_bus.publish(
                    {
                        "kind": "stream",
                        "address": "/unreal/start_audio",
                        "params": [str(output_path), ollama_result.get("model", "")],
                        "source": "platform",
                        "protocol": "internal",
                        "direction": "outbound",
                    }
                )
                logger.info(
                    "Unreal audio loop generated clip: model=%s file=%s latest=%s",
                    ollama_result.get("model"),
                    output_path,
                    latest_path,
                )
                await asyncio.sleep(UNREAL_AUDIO_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logger.info("Unreal audio loop cancelled.")
            raise
        except Exception:
            logger.exception("Unexpected Unreal audio loop failure.")

    def start_audio_loop(self, trigger: str) -> bool:
        if self._ctx.unreal_audio_task is not None and not self._ctx.unreal_audio_task.done():
            return False
        self._ctx.unreal_audio_task = asyncio.create_task(self.run_audio_loop(trigger))
        return True

    async def stop_audio_loop(self) -> bool:
        if self._ctx.unreal_audio_task is None or self._ctx.unreal_audio_task.done():
            self._ctx.unreal_audio_task = None
            return False
        self._ctx.unreal_audio_task.cancel()
        try:
            await self._ctx.unreal_audio_task
        except asyncio.CancelledError:
            pass
        self._ctx.unreal_audio_task = None
        return True

    async def route_command(self, payload: UnrealEventPayload, request_id: str) -> dict:
        command = normalize_unreal_command(payload.message)
        action = "none"
        changed = False
        details: dict = {}

        if command == "start audio":
            action = "start_audio"
            changed = self.start_audio_loop(trigger=f"unreal:{request_id}")
            details["audio_loop_running"] = (
                self._ctx.unreal_audio_task is not None and not self._ctx.unreal_audio_task.done()
            )
        elif command == "stop audio":
            action = "stop_audio"
            changed = await self.stop_audio_loop()
            details["audio_loop_running"] = (
                self._ctx.unreal_audio_task is not None and not self._ctx.unreal_audio_task.done()
            )
        elif command == "start image":
            action = "start_image"
            if self._ctx.unreal_image_task is not None and not self._ctx.unreal_image_task.done():
                details["image_task_running"] = True
            else:
                self._ctx.unreal_image_task = asyncio.create_task(
                    self.execute_image_generation(trigger=f"unreal:{request_id}")
                )
                changed = True
                details["image_task_running"] = True
        elif command == "agent start":
            action = "agent_start"
            changed = self._ctx.master_agent.start()
        elif command == "agent stop":
            action = "agent_stop"
            changed = self._ctx.master_agent.stop()

        return {
            "action": action,
            "changed": changed,
            "details": details,
        }

    async def cancel_tasks(self) -> None:
        if self._ctx.unreal_audio_task is not None and not self._ctx.unreal_audio_task.done():
            self._ctx.unreal_audio_task.cancel()
            try:
                await self._ctx.unreal_audio_task
            except asyncio.CancelledError:
                pass
            self._ctx.unreal_audio_task = None

        if self._ctx.unreal_image_task is not None and not self._ctx.unreal_image_task.done():
            self._ctx.unreal_image_task.cancel()
            try:
                await self._ctx.unreal_image_task
            except asyncio.CancelledError:
                pass
            self._ctx.unreal_image_task = None

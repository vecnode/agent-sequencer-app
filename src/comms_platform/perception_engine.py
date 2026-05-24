import re
from dataclasses import dataclass
from typing import Any
from urllib.request import Request, urlopen

import json

from .utils.logger import get_logger

logger = get_logger("master.agent.perception")


@dataclass
class PerceptionDecision:
    intent: str
    confidence: float
    route: str
    reason: str
    tool_name: str | None = None
    scores: dict[str, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "confidence": self.confidence,
            "route": self.route,
            "reason": self.reason,
            "tool_name": self.tool_name,
            "scores": self.scores or {},
        }


class PerceptionEngine:
    """Classify inbound text into chat vs tool intent using Ollama."""

    def __init__(
        self,
        ollama_base_url: str,
        model_name: str | None = None,
        confidence_threshold: float = 0.7,
        uncertain_threshold: float = 0.45,
        enabled: bool = True,
    ) -> None:
        self._ollama_base_url = ollama_base_url.rstrip("/")
        self._enabled = enabled
        self._model_name = (model_name or "").strip() or None
        self._confidence_threshold = confidence_threshold
        self._uncertain_threshold = uncertain_threshold
        self._cached_model_name: str | None = None
        self._model_load_error: str | None = None
        if self._enabled:
            self._try_connect_model()
        else:
            self._model_load_error = "perception_engine_disabled"

    def classify(self, text: str, selected_model: str | None = None) -> PerceptionDecision:
        clean_text = text.strip()
        if not clean_text:
            return PerceptionDecision(
                intent="chat",
                confidence=1.0,
                route="chat",
                reason="empty_input_fallback",
                scores={"chat": 1.0, "tool": 0.0},
            )

        if not self._enabled:
            return PerceptionDecision(
                intent="unavailable",
                confidence=0.0,
                route="chat",
                reason="perception_model_unavailable",
                scores={"chat": 0.0, "tool": 0.0},
            )

        try:
            intent, model_used = self._classify_with_ollama(clean_text, selected_model=selected_model)
        except Exception as exc:
            logger.warning("Perception model scoring failed; routing disabled: %s", exc)
            return PerceptionDecision(
                intent="unavailable",
                confidence=0.0,
                route="chat",
                reason="perception_model_unavailable",
                scores={"chat": 0.0, "tool": 0.0},
            )

        if intent not in {"chat", "tool"}:
            return PerceptionDecision(
                intent="unavailable",
                confidence=0.0,
                route="chat",
                reason="perception_model_unavailable",
                scores={"chat": 0.0, "tool": 0.0},
            )

        scores = {"chat": 1.0 if intent == "chat" else 0.0, "tool": 1.0 if intent == "tool" else 0.0}
        confidence = 1.0
        logger.info(
            "Perception classification via Ollama: model=%s intent=%s text=%r",
            model_used,
            intent,
            clean_text,
        )

        if intent == "tool" and confidence >= self._confidence_threshold:
            tool_name = self._extract_tool_name(clean_text)
            if tool_name:
                return PerceptionDecision(
                    intent="tool",
                    confidence=confidence,
                    route="tool",
                    reason="tool_confident",
                    tool_name=tool_name,
                    scores=scores,
                )
            return PerceptionDecision(
                intent="tool",
                confidence=confidence,
                route="chat",
                reason="tool_parse_failed",
                scores=scores,
            )

        return PerceptionDecision(
            intent=intent,
            confidence=confidence,
            route="chat",
            reason="default_chat_route",
            scores=scores,
        )

    def _try_connect_model(self) -> None:
        try:
            model = self._resolve_model_name(None)
            if not model:
                raise RuntimeError("No Ollama model available for perception")
            self._cached_model_name = model
            self._model_load_error = None
            logger.info("Perception engine model loaded (Ollama): %s", model)
        except Exception as exc:
            self._model_load_error = str(exc)
            logger.warning("Perception model failed to load: %s", exc)

    def _resolve_model_name(self, selected_model: str | None) -> str | None:
        if selected_model and selected_model.strip():
            return selected_model.strip()
        if self._model_name:
            return self._model_name
        if self._cached_model_name:
            return self._cached_model_name

        req = Request(f"{self._ollama_base_url}/api/tags", method="GET")
        with urlopen(req, timeout=5.0) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
        models = body.get("models", []) if isinstance(body, dict) else []
        if not models:
            return None
        first = models[0]
        if not isinstance(first, dict):
            return None
        name = str(first.get("name", "")).strip()
        if not name:
            return None
        self._cached_model_name = name
        return name

    def _classify_with_ollama(self, text: str, selected_model: str | None = None) -> tuple[str, str]:
        model_name = self._resolve_model_name(selected_model)
        if not model_name:
            raise RuntimeError("No Ollama model available for perception classification")

        prompt = (
            "You are an intent classifier for an agent control UI. "
            "Reply with exactly one lowercase word and nothing else: chat or tool. "
            "Use tool only if the user is asking to execute an action/function/command in the system. "
            "Otherwise use chat.\n"
            f"User message: {text}\n"
            "Answer:"
        )
        payload = {
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0,
            },
        }
        req = Request(
            f"{self._ollama_base_url}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=15.0) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))

        raw = str(body.get("response", "")).strip().lower()
        normalized = re.sub(r"[^a-z]", "", raw)
        if normalized in {"chat", "tool"}:
            return normalized, model_name
        if normalized.startswith("chat"):
            return "chat", model_name
        if normalized.startswith("tool"):
            return "tool", model_name
        raise RuntimeError(f"Invalid perception classification from Ollama: {raw!r}")

    def _extract_tool_name(self, text: str) -> str | None:
        lowered = re.sub(r"\s+", " ", text.lower()).strip()

        if "broadcast" in lowered and ("off" in lowered or "disable" in lowered):
            return "broadcast_off"
        if "broadcast" in lowered and ("on" in lowered or "enable" in lowered):
            return "broadcast_on"
        if "stop" in lowered and "agent" in lowered:
            return "agent_stop"
        if "start" in lowered and "agent" in lowered:
            return "agent_start"
        if "run" in lowered and "example" in lowered:
            return "agent_start"
        return None

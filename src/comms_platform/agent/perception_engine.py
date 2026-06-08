from dataclasses import dataclass
from typing import Any, Literal

import instructor
from ollama import Client
from openai import OpenAI
from pydantic import BaseModel, Field, model_validator

from .tool_registry import ToolRegistry
from ..utils.logger import get_logger

logger = get_logger("master.agent.perception")

ALLOWED_TOOL_NAMES = ToolRegistry.perception_tool_names()

SYSTEM_PROMPT = f"""You are an intent classifier for an agent control platform.

Classify the user message into one of two intents:
- chat: general conversation, questions, or instructions that do not execute a platform action
- tool: the user wants to execute a specific platform action

{ToolRegistry.build_perception_tools_prompt()}

Return a confidence score between 0.0 and 1.0.
Use tool only when the user clearly wants one of the listed actions.
When intent is tool, tool_name MUST be set to the matching tool (agent_start or agent_stop)."""


class IntentClassification(BaseModel):
    intent: Literal["chat", "tool"]
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence in the selected intent.",
    )
    tool_name: Literal["agent_start", "agent_stop"] | None = Field(
        default=None,
        description="Required when intent is tool; must be agent_start or agent_stop.",
    )

    @model_validator(mode="after")
    def require_tool_name_for_tool_intent(self) -> "IntentClassification":
        if self.intent == "tool" and self.tool_name is None:
            raise ValueError("tool_name is required when intent is tool")
        return self


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
    """Classify inbound text using Instructor structured output against local Ollama only."""

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
        self._instructor_client: instructor.Instructor | None = None
        self._instructor_model_name: str | None = None
        self._ollama_client = Client(host=self._ollama_base_url)
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
            classification, model_used = self._classify_with_instructor(clean_text, selected_model=selected_model)
        except Exception as exc:
            logger.warning("Perception model scoring failed; routing disabled: %s", exc)
            return PerceptionDecision(
                intent="unavailable",
                confidence=0.0,
                route="chat",
                reason="perception_model_unavailable",
                scores={"chat": 0.0, "tool": 0.0},
            )

        intent = classification.intent
        confidence = float(classification.confidence)
        tool_name = classification.tool_name
        if intent == "tool" and tool_name not in ALLOWED_TOOL_NAMES:
            inferred = ToolRegistry.infer_tool_name_from_text(clean_text)
            if inferred:
                tool_name = inferred
                logger.info("Perception inferred tool_name=%s from text=%r", tool_name, clean_text)
        scores = {
            "chat": confidence if intent == "chat" else 1.0 - confidence,
            "tool": confidence if intent == "tool" else 1.0 - confidence,
        }

        logger.info(
            "Perception classification via Instructor/Ollama: model=%s intent=%s confidence=%.3f tool=%s text=%r",
            model_used,
            intent,
            confidence,
            tool_name,
            clean_text,
        )

        if confidence < self._uncertain_threshold:
            return PerceptionDecision(
                intent=intent,
                confidence=confidence,
                route="chat",
                reason="low_confidence",
                tool_name=tool_name,
                scores=scores,
            )

        if intent == "tool" and confidence >= self._confidence_threshold:
            if tool_name in ALLOWED_TOOL_NAMES:
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
                tool_name=tool_name,
                scores=scores,
            )

        return PerceptionDecision(
            intent=intent,
            confidence=confidence,
            route="chat",
            reason="default_chat_route",
            tool_name=tool_name,
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

        response = self._ollama_client.list()
        models = getattr(response, "models", None) or []
        if not models:
            return None

        first = models[0]
        name = str(getattr(first, "model", "") or "").strip()
        if not name:
            return None

        self._cached_model_name = name
        return name

    def _build_instructor_client(self, model_name: str) -> instructor.Instructor:
        if self._instructor_client is not None and self._instructor_model_name == model_name:
            return self._instructor_client

        # OpenAI SDK is used only as HTTP transport to the local Ollama /v1 API.
        # max_retries=0 disables transport retries; no cloud OpenAI calls are made.
        ollama_transport = OpenAI(
            base_url=f"{self._ollama_base_url}/v1",
            api_key="ollama",
            max_retries=0,
        )
        client = instructor.from_openai(
            ollama_transport,
            model=model_name,
            mode=instructor.Mode.JSON_SCHEMA,
        )
        self._instructor_client = client
        self._instructor_model_name = model_name
        return client

    def _classify_with_instructor(
        self,
        text: str,
        selected_model: str | None = None,
    ) -> tuple[IntentClassification, str]:
        model_name = self._resolve_model_name(selected_model)
        if not model_name:
            raise RuntimeError("No Ollama model available for perception classification")

        client = self._build_instructor_client(model_name)
        classification = client.create(
            response_model=IntentClassification,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
        )
        return classification, model_name

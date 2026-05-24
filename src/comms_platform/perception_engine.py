import re
from dataclasses import dataclass
from typing import Any

from .utils.logger import get_logger

logger = get_logger("master.agent.intent")


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
    """Classify inbound text into chat vs tool intent using embeddings when available."""

    _DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

    def __init__(
        self,
        model_name: str | None = None,
        confidence_threshold: float = 0.7,
        uncertain_threshold: float = 0.45,
        enabled: bool = True,
    ) -> None:
        self._enabled = enabled
        self._model_name = model_name or self._DEFAULT_MODEL
        self._confidence_threshold = confidence_threshold
        self._uncertain_threshold = uncertain_threshold
        self._encoder = None
        self._prototype_vectors: dict[str, Any] = {}
        self._prototypes = {
            "chat": [
                "let us discuss this",
                "explain this to me",
                "what do you think about this",
                "chat with me about this",
            ],
            "tool": [
                "start the agent",
                "stop the agent",
                "turn broadcast on",
                "send a signal to touchdesigner",
                "run this action now",
            ],
        }
        if self._enabled:
            self._try_load_encoder()

    def classify(self, text: str) -> PerceptionDecision:
        clean_text = text.strip()
        if not clean_text:
            return PerceptionDecision(
                intent="chat",
                confidence=1.0,
                route="chat",
                reason="empty_input_fallback",
                scores={"chat": 1.0, "tool": 0.0},
            )

        scores = self._score_text(clean_text)
        best_intent = max(scores, key=scores.get)
        confidence = float(scores[best_intent])

        if confidence < self._uncertain_threshold:
            return PerceptionDecision(
                intent=best_intent,
                confidence=confidence,
                route="chat",
                reason="low_confidence_fallback",
                scores=scores,
            )

        if best_intent == "tool" and confidence >= self._confidence_threshold:
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
            intent=best_intent,
            confidence=confidence,
            route="chat",
            reason="default_chat_route",
            scores=scores,
        )

    def _try_load_encoder(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer

            self._encoder = SentenceTransformer(self._model_name)
            for intent, examples in self._prototypes.items():
                self._prototype_vectors[intent] = self._encoder.encode(examples)
            logger.info("Intent engine model loaded: %s", self._model_name)
        except Exception as exc:
            self._encoder = None
            logger.info("Intent engine falling back to heuristic mode: %s", exc)

    def _score_text(self, text: str) -> dict[str, float]:
        if self._encoder is None:
            return self._heuristic_scores(text)

        try:
            from sentence_transformers.util import cos_sim

            vector = self._encoder.encode([text])
            scores: dict[str, float] = {}
            for intent, prototype_vectors in self._prototype_vectors.items():
                similarity = cos_sim(vector, prototype_vectors)
                scores[intent] = float(similarity.max().item())
            return scores
        except Exception as exc:
            logger.info("Intent engine scoring fallback to heuristics: %s", exc)
            return self._heuristic_scores(text)

    def _heuristic_scores(self, text: str) -> dict[str, float]:
        lowered = text.lower()
        tool_hits = 0
        chat_hits = 0

        tool_terms = (
            "start",
            "stop",
            "run",
            "trigger",
            "execute",
            "send",
            "broadcast",
            "turn on",
            "turn off",
        )
        chat_terms = (
            "what",
            "why",
            "how",
            "explain",
            "think",
            "chat",
            "tell me",
            "help me understand",
        )

        for term in tool_terms:
            if term in lowered:
                tool_hits += 1
        for term in chat_terms:
            if term in lowered:
                chat_hits += 1

        # Keep scores bounded in [0,1] for predictable thresholds.
        tool_score = min(0.2 + 0.18 * tool_hits, 0.95)
        chat_score = min(0.2 + 0.18 * chat_hits, 0.95)

        if tool_hits == 0 and chat_hits == 0:
            chat_score = 0.51
            tool_score = 0.49

        return {"chat": chat_score, "tool": tool_score}

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
        return None

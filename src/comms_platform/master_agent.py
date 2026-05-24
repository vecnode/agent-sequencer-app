import threading
import time

from .perception_engine import PerceptionDecision, PerceptionEngine
from .utils.logger import get_logger

logger = get_logger("master.agent")


class MasterAgent:
    """Single master agent that maintains heartbeat and routes message intent."""

    def __init__(self, config=None) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event: threading.Event | None = None
        self._lock = threading.Lock()
        self._heartbeat_count = 0
        self._broadcast_enabled = False
        self._history_text_read: list[str] = []
        self._last_intent_decision: PerceptionDecision | None = None
        self._intent_engine = PerceptionEngine(
            model_name=getattr(config, "INTENT_MODEL_NAME", None),
            confidence_threshold=getattr(config, "INTENT_CONFIDENCE_THRESHOLD", 0.7),
            uncertain_threshold=getattr(config, "INTENT_UNCERTAIN_THRESHOLD", 0.45),
            enabled=getattr(config, "INTENT_ENGINE_ENABLED", True),
        )

    def start(self) -> bool:
        """Start the agent loop. Returns False when already running."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False

            self._stop_event = threading.Event()
            self._thread = threading.Thread(
                target=self._run,
                args=(self._stop_event,),
                daemon=True,
                name="master-agent",
            )
            self._thread.start()

        logger.info("Master agent started.")
        return True

    def stop(self, timeout: float = 2.0) -> bool:
        """Stop the agent loop. Returns False when it was not running."""
        with self._lock:
            thread = self._thread
            stop_event = self._stop_event
            if not thread or not thread.is_alive() or not stop_event:
                return False
            stop_event.set()

        thread.join(timeout)

        with self._lock:
            self._thread = None
            self._stop_event = None

        logger.info("Master agent stopped.")
        return True

    @property
    def is_running(self) -> bool:
        with self._lock:
            return bool(self._thread and self._thread.is_alive())

    @property
    def heartbeat_count(self) -> int:
        with self._lock:
            return self._heartbeat_count

    @property
    def broadcast_enabled(self) -> bool:
        with self._lock:
            return self._broadcast_enabled

    def set_broadcast(self, enabled: bool) -> bool:
        with self._lock:
            self._broadcast_enabled = enabled
            return self._broadcast_enabled

    @property
    def history_text_read(self) -> list[str]:
        with self._lock:
            return list(self._history_text_read)

    @property
    def last_intent_decision(self) -> dict | None:
        with self._lock:
            if self._last_intent_decision is None:
                return None
            return self._last_intent_decision.to_dict()

    def handle_human_message(self, text: str) -> str:
        clean_text = text.strip()
        with self._lock:
            self._history_text_read.append(clean_text)

        decision = self._intent_engine.classify(clean_text)
        with self._lock:
            self._last_intent_decision = decision

        if decision.route == "tool" and decision.tool_name:
            self._dispatch_tool(decision.tool_name)

        logger.info(
            "Master agent routed message: intent=%s route=%s confidence=%.3f tool=%s",
            decision.intent,
            decision.route,
            decision.confidence,
            decision.tool_name,
        )
        return "ok."

    def _dispatch_tool(self, tool_name: str) -> None:
        if tool_name == "agent_start":
            self.start()
            return
        if tool_name == "agent_stop":
            self.stop()
            return
        if tool_name == "broadcast_on":
            self.set_broadcast(True)
            return
        if tool_name == "broadcast_off":
            self.set_broadcast(False)
            return
        logger.info("Tool routing skipped unknown tool: %s", tool_name)

    def _run(self, stop_event: threading.Event) -> None:
        while not stop_event.wait(1.0):
            # Placeholder processing loop; real receive/process work can be plugged in here.
            with self._lock:
                self._heartbeat_count += 1
                beat = self._heartbeat_count
            logger.info("Master agent heartbeat %s", beat)


# Backward-compatible alias while references are being migrated.
AgentCoordinator = MasterAgent

import sys
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from comms_platform.web.app import EventBus, create_app


class StubThreadManager:
    def kill_all(self):
        pass


class StubAgentCoordinator:
    def __init__(self):
        self._running = False
        self.heartbeat_count = 0
        self._history_text_read: list[str] = []

    @property
    def is_running(self):
        return self._running

    def start(self):
        if self._running:
            return False
        self._running = True
        return True

    def stop(self):
        if not self._running:
            return False
        self._running = False
        return True

    @property
    def history_text_read(self):
        return list(self._history_text_read)

    def handle_human_message(self, text: str, selected_model: str | None = None):
        self._history_text_read.append(text.strip())
        return "ok."


class StubSignalGateway:
    osc_output_host = "127.0.0.1"
    osc_output_port = 9000
    osc_input_host = "0.0.0.0"
    osc_input_port = 9001

    def __init__(self):
        self.published: list[dict] = []
        self.enqueued: list[dict] = []

    def publish_stream(self, **kwargs):
        self.published.append(kwargs)

    def enqueue(self, **kwargs):
        self.enqueued.append(kwargs)


def build_client() -> TestClient:
    app = create_app(
        event_bus=EventBus(),
        thread_manager=StubThreadManager(),
        signal_gateway=StubSignalGateway(),
        master_agent=StubAgentCoordinator(),
    )
    return TestClient(app)


def log_test(test_name: str, details: str) -> None:
    print(f"[TEST] {test_name} | {details}", flush=True)

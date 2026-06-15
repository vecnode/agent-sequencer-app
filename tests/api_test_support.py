import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from comms_platform.config import Config
from comms_platform.web.app import create_app


class TestConfig(Config):
    ENGINES_PRELOAD_ON_STARTUP = False


def build_client() -> TestClient:
    app = create_app(config=TestConfig())
    return TestClient(app)


def log_test(test_name: str, details: str) -> None:
    print(f"[TEST] {test_name} | {details}", flush=True)

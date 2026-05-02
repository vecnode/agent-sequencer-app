# sequence-orchestrator

Sequence orcestrator, under development. 

### Reproduce

```sh
# Windows
.\run_platform.bat

# 1. Install dependencies (creates .venv in this folder)
uv venv
uv pip install -r requirements.txt

# 2. Run the platform
uv pip install -e .
uv run python -m comms_platform.main
```

## Testing

Run API tests with uv:

```sh
# Run all tests
uv run pytest -q -s

# Run only API tests
uv run pytest -q -s tests/test_api.py
```

The API tests include:
- `GET /health` — liveness endpoint, validates status and service name
- `GET /api/status` — server active status, SSE clients, OSC in/out addresses
- `POST /api/signals/publish` — stream publish accepted, gateway called with correct args
- `POST /api/signals/send` (stream) — stream transport selected, publish_stream invoked
- `POST /api/signals/send` (osc) — OSC transport selected, enqueue invoked, target address returned


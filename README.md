# agent-sequencer-app

Under development. 

This repository has the template to start building sequencer LLM agents (SLLMA). SLLMAs are agents able to execute tools but coordinate them for multimodal generation.

Coordination is mandatory for critical environments.

## Reproduce (Host)

```sh
# Windows
.\run_platform.bat

# 1. Install dependencies (creates .venv in this folder)
uv venv
uv pip install -r requirements.txt

# 2. Install this repo in editable mode
uv pip install -e .

# 3. Run the platform
uv run python -m comms_platform.main
```


## Docker (Windows)

```sh
future
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
- `POST /api/touchdesigner/run-example` — launches `touchdesigner/example1.toe`


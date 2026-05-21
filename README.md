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


## Docker (build)

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

## API

Current API endpoints:

- `GET /` — serves the web UI
- `GET /health` — liveness endpoint
- `GET /api/status` — runtime status (SSE clients, OSC in/out, agent state)
- `GET /api/ollama/status` — checks Ollama availability and lists models
- `GET /events` — SSE stream for frontend realtime events/logs

- `POST /api/agent/start` — starts agent coordinator
- `POST /api/agent/stop` — stops agent coordinator
- `POST /api/agent/broadcast/on` — enables agent broadcast
- `POST /api/agent/broadcast/off` — disables agent broadcast

- `POST /api/signals/publish` — publishes a stream signal to frontend/event bus
- `POST /api/signals/send` — sends signal (OSC when `protocol=osc`, otherwise stream)

- `POST /api/touchdesigner/run-example` — launches `touchdesigner/example1.toe`
- `POST /api/touchdesigner/send-test-data` — sends JSON payload to TouchDesigner web server (`TD_WEB_HOST:TD_WEB_PORT`)

- `POST /api/ollama/open` — opens configured Ollama target URL in default system handler

API tests currently cover core and integration-safe routes (health/status, signals, agent controls, TouchDesigner/Ollama status/open).


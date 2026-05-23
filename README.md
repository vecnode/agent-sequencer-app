# agent-sequencer-app

Under active development. 

This repository contains a professional agent-based multimodal communications platform. The system coordinates a master agent with realtime monitoring and browser UI.

Development Guidelines:

- Coordination is mandatory for critical environments.
- Traceable platform execution with accurate timings.
- A master agent controls and is accessed by the platform.

## Reproduce (Host)

```sh
# Windows
.\run_platform.bat

# 1. Manually
uv venv
uv pip install -r requirements.txt

# 2. Install this repo in editable mode
uv pip install -e .

# 3. Run the platform
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


## Docker (build)

```sh
future
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
- `POST /api/agent/message` — sends human text to the agent, appends to history, and returns current reply

- `POST /api/signals/publish` — publishes a stream signal to frontend/event bus
- `POST /api/signals/send` — sends signal (OSC when `protocol=osc`, otherwise stream)

- `POST /api/touchdesigner/run-example` — launches `touchdesigner/example1.toe`
- `POST /api/touchdesigner/send-test-data` — sends JSON payload to TouchDesigner web server (`TD_WEB_HOST:TD_WEB_PORT`)
- `GET /api/touchdesigner/processes` — lists running TouchDesigner processes on this machine


API tests currently cover core and integration-safe routes (health/status, signals, agent controls, TouchDesigner/Ollama status/open).

## Repository Structure

```text
.
|-- LICENSE
|-- README.md
|-- pyproject.toml
|-- requirements.txt
|-- run_platform.bat
|-- docker/ (containerization resources)
|   `-- README.md
|-- docs/ (project documentation)
|   `-- README.md
|-- src/ (application source code)
|   |-- comms_platform/ (core platform package)
|   |   |-- __init__.py
|   |   |-- agent_coordinator.py
|   |   |-- config.py
|   |   |-- inference_worker.py
|   |   |-- main.py
|   |   |-- td_sender.py
|   |   |-- thread_manager.py
|   |   |-- utils/ (shared utilities)
|   |   |   |-- __init__.py
|   |   |   `-- logger.py
|   |   `-- web/ (FastAPI web server and UI)
|   |       |-- __init__.py
|   |       |-- app.py
|   |       `-- static/ (frontend assets)
|   |           |-- index.html
|   |           |-- main.js
|   |           `-- styles.css
|-- tests/ (automated test suite)
|   |-- README.md
|   `-- test_api.py
`-- touchdesigner/ (TouchDesigner project files)
    |-- README.md
    |-- example1.toe
    `-- python1.py
```


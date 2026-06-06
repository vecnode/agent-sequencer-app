# agent-sequencer-app

Under active development. 

This repository contains a professional agent-based multimodal communications platform. The system coordinates a master agent with realtime monitoring and browser UI. For LLMs, relies on Ollama, for TTS on Supertonic 3.

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

## Blocks

<details>
<summary>Block 01 - Agent</summary>

- Starts and stops the master agent.
- Shows current agent state.
- Uses the top-left control block for core runtime control.
</details>

<details>
<summary>Block 02 - Terminal</summary>

- Shows backend logs, stream events, and agent replies.
- Acts as the main realtime output surface.
- Useful for tracing platform activity and request flow.
</details>

<details>
<summary>Block 03 - Agent State</summary>

- Displays a JSON snapshot of the current runtime state.
- Can be scoped to agent, stream, connections, TouchDesigner, Ollama, or UI.
- Includes refresh and copy controls for debugging.
</details>

<details>
<summary>Block 04 - Engines</summary>

- Launches TouchDesigner example workflows.
- Checks TouchDesigner process state.
- Sends test data and UE5 bridge messages.
</details>

<details>
<summary>Block 05 - Ollama</summary>

- Checks whether Ollama is reachable on the host.
- Opens Ollama from the installed Windows executable when available.
- Lets you pick an available Ollama model for agent chat.
</details>

<details>
<summary>Block 06 - Inference</summary>

- Hosts two inference modules in a single control surface.
- SuperTonic 3: load/unload TTS engine and monitor engine status.
- SDXL Base 1: load/unload image pipeline, submit prompts, and preview generated images.
</details>

<details>
<summary>Block 07 - User Input</summary>

- Sends text payloads to the backend agent.
- Creates the main human-to-agent message path.
- Appends the user message and agent reply into the terminal view.
</details>


## API

Current API endpoints and capabilities:

- `GET /` — serves the web UI
- `GET /health` — liveness endpoint
- `GET /events` — SSE stream for frontend realtime events/logs
- `GET /api/status` — runtime status (SSE clients, OSC in/out, agent state)

- `POST /api/signals/publish` — publishes a stream signal to frontend/event bus
- `POST /api/signals/send` — sends signal (OSC when `protocol=osc`, otherwise stream)


- `POST /api/agent/start` — starts agent coordinator
- `POST /api/agent/stop` — stops agent coordinator
- `POST /api/agent/message` — sends human text to the agent, appends to history, and returns the current reply plus routing/LLM metadata

- `GET /api/ollama/status` — checks Ollama availability and lists models
- `POST /api/ollama/open` — starts Ollama when installed locally

- `GET /api/tts/status` — reports whether SuperTonic 3 is loaded
- `POST /api/tts/engine/on` — loads SuperTonic 3 into memory for fast inference
- `POST /api/tts/engine/off` — unloads SuperTonic 3 from memory
- `POST /api/tts/synthesize` — synthesizes TTS audio using SuperTonic 3 and returns WAV audio

- `GET /api/sdxl/status` — reports whether SDXL Base 1 is loaded
- `POST /api/sdxl/engine/on` — loads SDXL Base 1 pipeline into memory
- `POST /api/sdxl/engine/off` — unloads SDXL Base 1 pipeline from memory
- `POST /api/sdxl/generate` — generates an image from prompt and returns preview payload + output file metadata



- `POST /api/touchdesigner/run-example` — launches `touchdesigner/example1.toe`
- `POST /api/touchdesigner/send-test-data` — sends JSON payload to TouchDesigner web server (`TD_WEB_HOST:TD_WEB_PORT`)
- `GET /api/touchdesigner/processes` — lists running TouchDesigner processes on this machine






## License

Licensed under the [MIT License](./LICENSE).
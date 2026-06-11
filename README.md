# ai-comms-platform

Under active development. 

This repository contains a communications platform with TTS, TTI, TT3D, and a master agent.  

Interop: with Unreal Engine, TouchDesigner, Ollama.  
Contains: Diffusers, XFormers, Triton, Instructor.  

- TTS model Supertonic 3
- TTI model SDXL-Base-1
- TT3D model [Hunyuan3D-2.1](https://huggingface.co/tencent/Hunyuan3D-2.1) (text → SDXL → shape → PBR texture → GLB)

Development Guidelines:

- A master agent controls and is accessed by the platform.
- Coordination is mandatory for critical environments.
- Expose API and execution timings.
- Local and field-first architecture

## Package layout

```
src/comms_platform/
├── main.py              # entry point
├── config.py
├── constants.py         # shared env defaults and paths
├── agent/               # master agent + perception engine
├── transport/           # EventBus, OSC gateway, thread manager
├── integrations/        # Ollama, TouchDesigner, Unreal orchestration
├── inference/           # TTS, TTI, and TT3D engines
├── utils/
├── mcp/                 # MCP server (Streamable HTTP)
└── web/
    ├── app.py           # FastAPI factory and lifespan
    ├── routes/          # HTTP route modules by domain
    ├── schemas.py
    └── static/          # dashboard UI (HTTP client)
```

## MCP control plane

The platform exposes a [Model Context Protocol](https://modelcontextprotocol.io) server alongside the existing REST API. MCP clients (Cursor, Claude Code, MCP Inspector) can start/stop the master agent, send natural-language messages, and read runtime state.

```mermaid
flowchart LR
    Browser["Browser UI\n(main.js)"]
    MCPClient["MCP Clients\n(Cursor, CLI)"]
    Platform["comms-platform\n(FastAPI + uvicorn)"]
    Agent["MasterAgent\n(in-process thread)"]
    Perception["PerceptionEngine\n(Instructor)"]
    Ollama["Ollama\n(separate LLM server)"]

    Browser -->|"HTTP /api/*"| Platform
    MCPClient -->|"Streamable HTTP /mcp"| Platform
    Platform --> Agent
    Agent --> Perception
    Perception -->|"Instructor → /v1"| Ollama
    Platform -->|"chat: /api/generate"| Ollama
```

### MCP tools

| Tool | Description |
|------|-------------|
| `agent_start` | Start the master agent heartbeat loop |
| `agent_stop` | Stop the master agent heartbeat loop |
| `agent_status` | Return current agent runtime status |
| `agent_message` | Natural-language input via perception routing and optional Ollama chat |

### MCP resources

| URI | Description |
|-----|-------------|
| `platform://agent/state` | JSON snapshot of agent and connection runtime state |
| `platform://agent/intent` | JSON snapshot of the latest perception routing decision |

### Connect from Cursor

With the platform running (default `http://127.0.0.1:8000`):

```json
{
  "mcpServers": {
    "communications-platform": {
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_ENABLED` | `true` | Enable MCP Streamable HTTP mount |
| `MCP_MOUNT_PATH` | `/mcp` | HTTP mount path for the MCP endpoint |

## Reproduce Windows

Requires Python 3.12 on Windows for the CUDA PyTorch wheel set used by SDXL.

```sh
# First time
uv venv
uv pip install -r requirements.txt
uv pip install -e .

.\run_platform.bat
```

`run_platform.bat` installs CUDA PyTorch, xFormers, triton-windows, applies Hunyuan3D vendor patches, and starts the platform. One-time Hunyuan3D vendor clone still required:

```powershell
.\scripts\setup_hunyuan3d.ps1
```

## TT3D (Hunyuan3D-2.1) setup

TT3D is optional and heavier than TTI/TTS. It chains your existing SDXL pipeline with Tencent's Hunyuan3D-2.1 shape and PBR paint stages to produce a textured GLB from a text prompt.

### Hardware

| Stage | VRAM (approx.) |
|-------|----------------|
| SDXL preflight (TTI) | 8–12 GB |
| Shape generation | 10 GB |
| PBR texture synthesis | 21 GB |
| Full pipeline | ~29 GB |

Use `TT3D_LOW_VRAM=true` (default) to unload each stage before loading the next. TTI and TT3D are mutually exclusive on the GPU by default (`TT3D_EXCLUSIVE_GPU=true`).

### One-time vendor install

From the repository root on Windows:

```powershell
.\scripts\setup_hunyuan3d.ps1
```

This script:

1. Clones [Tencent-Hunyuan/Hunyuan3D-2.1](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1) into `vendor/Hunyuan3D-2.1`
2. Installs platform dependencies (including TT3D packages such as `trimesh`, `rembg`, etc.)
3. Builds the `custom_rasterizer` CUDA extension
4. Downloads Real-ESRGAN weights for the paint pipeline

If texture generation fails after setup, compile the DifferentiableRenderer manually following the upstream README in `vendor/Hunyuan3D-2.1`.

Install dependencies manually:

```sh
uv pip install -e .
```

### TT3D environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HUNYUAN3D_ROOT` | `vendor/Hunyuan3D-2.1` | Path to the cloned Hunyuan3D repo |
| `TT3D_MODEL_ID` | `tencent/Hunyuan3D-2.1` | Hugging Face model ID |
| `TT3D_SHAPE_SUBFOLDER` | `hunyuan3d-dit-v2-1` | Shape model subfolder |
| `TT3D_DEFAULT_GUIDANCE` | `7.5` | Classifier-free guidance for shape |
| `TT3D_DEFAULT_STEPS` | `30` | Diffusion steps for shape |
| `TT3D_DEFAULT_OCTREE_RESOLUTION` | `256` | Mesh detail level |
| `TT3D_ENABLE_TEXTURE` | `true` | Run PBR paint stage (disable for shape-only) |
| `TT3D_LOW_VRAM` | `true` | Unload pipelines between stages |
| `TT3D_USE_INTERNAL_TTI` | `true` | Generate reference image via SDXL before shape |
| `TT3D_EXCLUSIVE_GPU` | `true` | Unload TTI when TT3D loads (and vice versa) |
| `TT3D_TEST_PROMPT` | wooden chair prompt | Default prompt before a global `prompt:` is set |

### Global inference prompt

Send `prompt: your text here` in **Block 08** or via MCP `agent_message` to set the shared prompt used by **Gen TTS**, **Gen TTI**, and **Gen TT3D**. Example:

```
prompt: a neon cyberpunk city at night
```

### Expected warnings on Windows

| Message | Severity | Meaning / fix |
|---------|----------|----------------|
| `No module named 'triton'` (from xformers) | Fixable | Official `triton` has no Windows wheel. Install **`triton-windows`** (included in `run_platform.bat` and `pyproject.toml` for Windows). Use version `<3.3` with PyTorch 2.6. Not conflicting with PyTorch — it provides the `triton` module xFormers probes for. |
| `No module named 'bpy'` | Python version gap | **`bpy` cannot be pip-installed on Python 3.12.** PyPI wheels exist only for **Python 3.11** (`bpy==5.0.1`) and **Python 3.13** (`bpy==5.1.2`). This project uses 3.12 for CUDA PyTorch wheels. |
| `Bpy IO CAN NOT BE Imported` | Usually harmless | Upstream optional import; patched automatically by the platform so the **PBR paint pipeline can load** without bpy. |
| `InPaint Function CAN NOT BE Imported` | Usually harmless | Optional inpaint helper missing; core paint path still runs. |
| `custom_rasterizer has no attribute 'rasterize'` or `No module named 'custom_rasterizer_kernel'` | **Must fix for textured output** | The Hunyuan **paint** CUDA extension was not compiled. Run `.\scripts\setup_hunyuan3d.ps1` with **Visual Studio Build Tools** and **CUDA 12.4** installed (must match PyTorch cu124). Until then TT3D can still export **shape-only** GLB. |

**Triton (recommended on Windows):**

```powershell
uv pip install "triton-windows>=3.2.0.post21,<3.3"
```

**bpy (not available on Python 3.12 via pip):**

```powershell
# Will FAIL on Python 3.12:
uv pip install bpy

# Works only on matching Python versions:
# Python 3.11 → uv pip install bpy==5.0.1
# Python 3.13 → uv pip install bpy==5.1.2
```

Without bpy, the platform patches Hunyuan3D's vendor code so **textured OBJ generation still works**; only Blender-native OBJ→GLB conversion is skipped (trimesh is used instead). Restart the platform after setup so the patch is applied before loading TT3D.

To hide texture attempts entirely: `TT3D_ENABLE_TEXTURE=false`

### TT3D generation flow

```mermaid
flowchart LR
    Prompt["Text prompt"] --> TTI["SDXL TTI\n(reference PNG)"]
    TTI --> RemBG["Background removal"]
    RemBG --> Shape["Hunyuan3D shape\n(DiT flow matching)"]
    Shape --> Paint["Hunyuan3D paint\n(PBR textures)"]
    Paint --> GLB["output/tt3d_latest.glb"]
```

Outputs are written to `output/`:

- `tt3d_latest.glb` — latest textured (or shape-only) model
- `tt3d_ref_latest.png` — SDXL reference image used for conditioning


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
- Can be scoped to agent (includes stream, connections, inference), third party, or timers.
- Includes refresh and copy controls for debugging.
</details>

<details>
<summary>Block 04 - Engines</summary>

- Launches TouchDesigner example workflows.
- Checks TouchDesigner process state.
- Sends test data and UE5 bridge messages.
- Checks whether Ollama is reachable on the host.
- Opens Ollama from the installed Windows executable when available.
- Lets you pick an available Ollama model for agent chat.
</details>

<details>
<summary>Block 05 - Media Viewer</summary>

- Shows latest generated media artifacts.
- Image card: TTI thumbnail preview, image path, and Open Image action.
- Audio card: TTS audio player, audio path, and Open Audio action.
- Model card: TT3D reference PNG preview (same style as TTI), path, and Open Model action (opens GLB in a new tab).
- Includes Refresh to reload latest media from backend endpoints.
</details>

<details>
<summary>Block 06 - Inference</summary>

- SuperTonic 3, SDXL Base 1, and Hunyuan3D 2.1: load/unload each engine and run **Gen TTS**, **Gen TTI**, or **Gen TT3D** using the current global inference prompt.
</details>

<details>
<summary>Block 07 - Timers</summary>

- Interval timers for TTS, TTI, and TT3D test renders.
- TTS/TTI: every 10 seconds or every 20 seconds.
- TT3D: every 60 seconds or every 120 seconds (generation is slower).
- Timer state is tracked in the agent state `timers` section.
</details>

<details>
<summary>Block 08 - User Input</summary>

- Sends text payloads to the backend agent or MCP.
- Use `prompt: your text` to set the shared inference prompt for Gen TTS, Gen TTI, and Gen TT3D.
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

- `MCP /mcp` — Streamable HTTP MCP endpoint (tools: `agent_start`, `agent_stop`, `agent_status`, `agent_message`; resources: `platform://agent/state`, `platform://agent/intent`)

- `POST /api/unreal/event` — ingests Unreal events and toggles agent start/stop based on current state
- `POST /api/platform/send-to-unreal` — sends a message to Unreal `/notify`

- `GET /api/ollama/status` — checks Ollama availability and lists models
- `POST /api/ollama/open` — starts Ollama when installed locally

- `GET /api/tts/status` — reports whether SuperTonic 3 is loaded
- `POST /api/tts/engine/on` — loads SuperTonic 3 into memory for fast inference
- `POST /api/tts/engine/off` — unloads SuperTonic 3 from memory
- `POST /api/tts/synthesize` — synthesizes TTS audio using SuperTonic 3 and returns WAV audio
- `POST /api/tts/test` — runs a quick TTS render and stores latest audio artifact

- `GET /api/tti/status` — reports whether SDXL Base 1 (TTI) is loaded
- `POST /api/tti/engine/on` — loads SDXL Base 1 pipeline into memory
- `POST /api/tti/engine/off` — unloads SDXL Base 1 pipeline from memory
- `POST /api/tti/generate` — generates an image from prompt and returns preview payload + output file metadata
- `POST /api/tti/test` — runs a quick TTI render and stores latest image artifact

- `GET /api/tt3d/status` — reports whether Hunyuan3D 2.1 is loaded and prerequisite checks
- `POST /api/tt3d/engine/on` — loads Hunyuan3D shape (and paint, when enabled) pipelines
- `POST /api/tt3d/engine/off` — unloads TT3D pipelines and clears GPU cache
- `POST /api/tt3d/generate` — one-shot text-to-3D: SDXL reference → shape → optional PBR → GLB
- `POST /api/tt3d/test` — runs a quick TT3D render with the default test prompt

- `GET /api/media/tti/latest` — serves `output/tti_latest.png` for UI/media viewer
- `GET /api/media/tts/latest` — serves `output/tts_latest.wav` for UI/media viewer
- `GET /api/media/tt3d/latest` — serves `output/tt3d_latest.glb` for UI/media viewer



- `POST /api/touchdesigner/run-example` — launches `touchdesigner/example1.toe`
- `POST /api/touchdesigner/send-test-data` — sends JSON payload to TouchDesigner web server (`TD_WEB_HOST:TD_WEB_PORT`)
- `GET /api/touchdesigner/processes` — lists running TouchDesigner processes on this machine


## Tests

Run tests with `uv` from the project root:

```sh
# New Unreal trigger HTTP tests (without external Unreal/TD software)
uv run pytest -q tests/test_api_unreal_start_audio.py
uv run pytest -q tests/test_api_unreal_start_image.py

# Live HTTP tests (send real POST requests to running API, watch backend console logs)
# Terminal 1: start platform
.\run_platform.bat

# Terminal 2: send live trigger requests via pytest
uv run pytest -q -s tests/test_http_unreal_live.py

# Optional: use a non-default API host/port
LIVE_API_BASE_URL=http://127.0.0.1:8000 uv run pytest -q -s tests/test_http_unreal_live.py

# Optional: run all API tests
uv run pytest -q tests/test_api_*.py
```





## License

Licensed under the [MIT License](./LICENSE).

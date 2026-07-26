# JacVerify

Graph-native, evidence-driven chip verification orchestrator built with Jac and open-source EDA tools.

The P0 demo is a seven-walker FIFO wraparound pipeline:

```text
LoadInputsWalker
→ CompileWalker
→ SimulateWalker
→ StructureFailureWalker
→ RankHypothesesWalker
→ GenerateArtifactWalker
→ ReverifyAndRenderWalker
```

The last two walkers can repeat for up to three ranked hypotheses. A known
`VERIFICATION_FAILED` result rejects the current hypothesis and selects the
next one. Three failures—or any unknown/tool-error condition—stop at
`NEEDS_USER_REVIEW`.

## Modes

| Variable | `1` | `0` / unset |
|---|---|---|
| `JACVERIFY_MOCK_TOOLS` | Deterministic mock tool adapters | Live Icarus Verilog (`iverilog` / `vvp`) |
| `JACVERIFY_MOCK_LLM` | Deterministic mock diagnosis / artifact | Live adapter selected by `JACVERIFY_LLM_BACKEND` |

The current experimental live backend is Firecrawl Agent (`spark-1-mini`).
Jac byLLM remains available as the fallback backend.

Mock adapters replace tool/LLM backends. They do **not** bypass walkers, graph updates, or transition logging.

There is **no silent fallback** from live tools to mock when a simulator is missing. Live mode returns `TOOL_ERROR` and the pipeline stops.

## Local dependency setup

Jac and cocotb use separate Python runtimes in this project:

- Jac 0.34.7 uses its bundled Python 3.14 runtime.
- cocotb 2.0.x supports Python through 3.13, so it lives in the repository's
  host-Python `.venv`.
- cocotb 2.0.x requires Verilator 5.036 or newer. This setup was verified with
  Verilator 5.050 on macOS ARM64.
- Icarus Verilog remains the live fallback used by the current adapter.

```bash
# Jac application, test, and React/Vite dependencies
jac install --dev
jac install byllm

# Verilator/cocotb environment (use Python 3.9-3.13)
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-eda.txt

jac --version
verilator --version
.venv/bin/cocotb-config --version
```

On macOS, pass `CXXFLAGS=-std=c++17` when building Verilator through the
cocotb runner.

## Fully mocked mode (no simulator, no API key)

```bash
jac install

JACVERIFY_MOCK_TOOLS=1 \
JACVERIFY_MOCK_LLM=1 \
jac start --dev main.jac
```

Open [http://localhost:8000](http://localhost:8000).

Upload path (product UX):

1. Choose an RTL module in **Design RTL**.
2. Choose its independent SystemVerilog testbench in **Testbench**.
3. Click **Run verification loop**, or use the curated FIFO pair.
4. Inspect the graph evidence at [http://localhost:8000/graph](http://localhost:8000/graph).

The compile and simulation commands use exactly the two uploaded files, saved
under that run's isolated `runs/<run-id>/inputs/` directory. Any valid
SystemVerilog module/test pair can run. Automatic candidate application remains
restricted to reviewed fixtures; an unrecognized failing design stops at
`NEEDS_USER_REVIEW` after recording tool evidence.

Coverage is optional and test-owned. A testbench can publish both metrics with:

```systemverilog
$display("JACVERIFY_COVERAGE code=82.5 functional=75.0");
```

JacVerify parses the last such marker and displays code and functional
coverage. If the test does not report coverage, the UI shows `N/A` rather than
inventing a value. Mock results are explicitly labeled `mock:testbench_marker`.

For a terminal-only demo:

```bash
scripts/run_demo.sh --mock
scripts/run_demo.sh --firecrawl
scripts/run_demo.sh --live-tools
```

`--firecrawl` is the default and uses mock EDA evidence with live Firecrawl
inference. Use `--live-tools` only after that succeeds.

## Live simulator with deterministic LLM

Requires Icarus Verilog (verified with 12.0):

```bash
brew install icarus-verilog

JACVERIFY_MOCK_TOOLS=0 \
JACVERIFY_MOCK_LLM=1 \
jac start --dev main.jac
```

Current simulator integration: **Icarus Verilog** (`iverilog` + `vvp`), not Verilator/cocotb.

## Experimental Firecrawl inference

Firecrawl is being tested as a constrained inference backend even though its
Agent API is designed primarily for web data gathering. Keep the key only in
the ignored local `.env`:

```bash
JACVERIFY_MOCK_LLM=0
JACVERIFY_LLM_BACKEND=firecrawl
FIRECRAWL_API_KEY=
JACVERIFY_FIRECRAWL_MODEL=spark-1-mini
JACVERIFY_FIRECRAWL_MAX_CREDITS=100
```

Each call submits a strict JSON schema and polls for completion. One demo run
uses one ranking job plus up to three artifact jobs. The adapter never allows
the response to select an RTL path or produce a verification PASS.

## Verify

```bash
JACVERIFY_MOCK_TOOLS=1 \
JACVERIFY_MOCK_LLM=1 \
JAC_DATA_PATH="$(mktemp -d)" \
jac test jacverify/store.jac -v

JACVERIFY_MOCK_TOOLS=1 \
JACVERIFY_MOCK_LLM=1 \
PYTHONPATH=. .venv/bin/python -m pytest tests/test_tool_adapter.py -q
```

## What is live vs mocked

- **Always Jac-orchestrated:** seven walkers, graph nodes/edges, transition records.
- **Tools:** mock `ToolResult` values when `JACVERIFY_MOCK_TOOLS=1`; otherwise Icarus compiles and runs the uploaded design/test pair.
- **LLM:** deterministic outputs in mock mode; Firecrawl Agent is the current experimental live adapter, with typed Jac byLLM retained as an alternative.
- **Fixed RTL:** `demo/fifo/fifo_fixed.sv` is a **pre-reviewed candidate fixture**, not an LLM-authored patch. Re-verification PASS comes only from the simulator `ToolResult`.

## Architecture

```text
Dashboard / run_uploaded_inputs
  → create fresh Run
  → LoadInputsWalker … ReverifyAndRenderWalker
      → ToolResult adapters (mock or Icarus)
      → constrained LLM wrappers (mock, Firecrawl Agent, or Jac byLLM)
      → Requirement / Module / Test / Run / Failure / Hypothesis / Artifact graph
```

Important entrypoints:

- `main.jac` — full-stack entry
- `jacverify/store.jac` — graph model, seven walkers, endpoints
- `jacverify/llm_calls.jac` — two constrained, typed byLLM declarations
- `jacverify/tool_adapter.py` — shared `ToolResult` + mock/live adapters
- `demo/fifo/` — buggy/fixed RTL, smoke + wrap testbenches, five requirements
- `Documents/JacVerify_LLM功能现状.md` — current LLM scope, setup, and remaining work

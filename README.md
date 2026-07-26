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

## Modes

| Variable | `1` | `0` / unset |
|---|---|---|
| `JACVERIFY_MOCK_TOOLS` | Deterministic mock tool adapters | Live Icarus Verilog (`iverilog` / `vvp`) |
| `JACVERIFY_MOCK_LLM` | Deterministic mock diagnosis / artifact | Live LLM (not configured in this build; set to `1`) |

Mock adapters replace tool/LLM backends. They do **not** bypass walkers, graph updates, or transition logging.

There is **no silent fallback** from live tools to mock when a simulator is missing. Live mode returns `TOOL_ERROR` and the pipeline stops.

## Fully mocked mode (no simulator, no API key)

```bash
jac install

JACVERIFY_MOCK_TOOLS=1 \
JACVERIFY_MOCK_LLM=1 \
jac start --dev main.jac
```

Open [http://localhost:8000](http://localhost:8000), stay on **FIFO evidence loop**, click **Run seven-walker loop**.

Inspect the graph evidence at [http://localhost:8000/graph](http://localhost:8000/graph).

## Live simulator with deterministic LLM

Requires Icarus Verilog 13+:

```bash
brew install icarus-verilog

JACVERIFY_MOCK_TOOLS=0 \
JACVERIFY_MOCK_LLM=1 \
jac start --dev main.jac
```

Current simulator integration: **Icarus Verilog** (`iverilog` + `vvp`), not Verilator/cocotb.

## Verify

```bash
JACVERIFY_MOCK_TOOLS=1 \
JACVERIFY_MOCK_LLM=1 \
JAC_DATA_PATH="$(mktemp -d)" \
jac test jacverify/store.jac -v

JACVERIFY_MOCK_TOOLS=1 \
JACVERIFY_MOCK_LLM=1 \
.jac/venv/bin/python -m pytest tests/test_tool_adapter.py -q
```

## What is live vs mocked

- **Always Jac-orchestrated:** seven walkers, graph nodes/edges, transition records.
- **Tools:** mock `ToolResult` values when `JACVERIFY_MOCK_TOOLS=1`; otherwise real Icarus compile/sim/reverify.
- **LLM:** deterministic ranked hypotheses + reviewed-candidate artifact description when `JACVERIFY_MOCK_LLM=1`.
- **Fixed RTL:** `demo/fifo/fifo_fixed.sv` is a **pre-reviewed candidate fixture**, not an LLM-authored patch. Re-verification PASS comes only from the simulator `ToolResult`.

## Architecture

```text
Dashboard / run_fifo_demo
  → create fresh Run
  → LoadInputsWalker … ReverifyAndRenderWalker
      → ToolResult adapters (mock or Icarus)
      → typed LLM wrappers (mock)
      → Requirement / Module / Test / Run / Failure / Hypothesis / Artifact graph
```

Important entrypoints:

- `main.jac` — full-stack entry
- `jacverify/store.jac` — graph model, seven walkers, endpoints
- `jacverify/tool_adapter.py` — shared `ToolResult` + mock/live adapters
- `demo/fifo/` — buggy/fixed RTL, smoke + wrap testbenches, five requirements

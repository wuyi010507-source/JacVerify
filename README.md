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

## Dependencies

### Python / Jac (pip + jac)

```bash
jac install
pip install -r requirements.txt
```

`requirements.txt` lists Python packages only.

### Icarus Verilog (system package — not pip)

`iverilog` / `vvp` are native binaries. They **cannot** be installed via `requirements.txt`.

| Environment | Install |
|---|---|
| Local macOS | `brew install icarus-verilog` |
| Local Ubuntu/Debian | `sudo apt-get install -y iverilog` |
| Deployed server / Docker | Install the same OS package in the image or host; ensure `iverilog` and `vvp` are on `PATH` |

- **Local live tool runs:** yes, install Icarus on your machine.
- **Deployed live tool runs:** yes, install Icarus on every runtime that sets `JACVERIFY_MOCK_TOOLS=0`.
- **Mock tool mode:** no Icarus needed (`JACVERIFY_MOCK_TOOLS=1`).

Check:

```bash
iverilog -V
vvp -V
```

Current simulator integration: **Icarus Verilog** (`iverilog` + `vvp`), not Verilator/cocotb.

## Fully mocked mode (no simulator, no API key)

```bash
jac install

JACVERIFY_MOCK_TOOLS=1 \
JACVERIFY_MOCK_LLM=1 \
jac start --dev main.jac
```

Open [http://localhost:8000](http://localhost:8000).

Upload path (product UX):

1. Choose one of `demo/fifo/fifo_buggy.sv`, `demo/alu/alu_buggy.sv`, or
   `demo/shift_reg/shift_reg_buggy.sv` in **Design upload**, or click **Use curated sample** (FIFO).
2. Click **Run verification loop**.
3. Inspect the graph evidence at [http://localhost:8000/graph](http://localhost:8000/graph).

Uploads are real file reads. Execution is allow-listed to curated hackathon cases so the demo stays reliable. Unknown RTL is rejected with an explicit message (no silent fallback).

## Live simulator with deterministic LLM

```bash
brew install icarus-verilog   # once, locally

JACVERIFY_MOCK_TOOLS=0 \
JACVERIFY_MOCK_LLM=1 \
jac start --dev main.jac
```

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
- **Fixed RTL:** `demo/*/…_fixed.sv` files are **pre-reviewed candidate fixtures**, not LLM-authored patches. Re-verification PASS comes only from the simulator `ToolResult`.

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
- `demo/fifo/` — FIFO wraparound case (buggy/fixed RTL, smoke + wrap TB, five requirements)
- `demo/alu/` — ALU SUB-opcode case (same shape as FIFO)
- `demo/shift_reg/` — shift-register direction case (same shape as FIFO)

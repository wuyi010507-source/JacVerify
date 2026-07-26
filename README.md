# JacVerify

JacVerify is an evidence-driven verification decision layer for chip verification teams. It answers two connected questions:

1. **Project view:** Which verification action is most valuable next, given risk, evidence, urgency, and compute cost?
2. **Task view:** How can that action move through an observable, recoverable, and auditable verification loop?

Jac is the center of the system—not a wrapper. Jac nodes and edges store project and verification state; `ProjectPlanner` traverses the graph to rank actions; `StateExecutor` drives the FIFO verification FSM; typed Jac endpoints connect the graph to a Jac client UI.

## Live demo story

The demo starts with three candidate actions:

- **Module A · FIFO:** a high-confidence wraparound failure cluster with low reverify cost.
- **Module B · Coverage:** broad random regression is producing little marginal coverage.
- **Module C · Environment:** failures match a configuration signature, so changing RTL would be unsupported.

JacVerify ranks Module A first. The operator then runs an executable FIFO evidence loop:

1. Load five requirements from `demo/fifo/fifo_spec.md`.
2. Compile and smoke-test the buggy RTL with Icarus Verilog.
3. Reproduce a real `WRAP_MISMATCH`.
4. Record a model-inference step and a bounded action recommendation.
5. Run the same directed test against a pre-approved patch fixture.
6. Record a real `WRAP_TEST_PASS` and complete the FSM.

The UI labels **tool facts**, **model inferences**, **action recommendations**, and **scenario data** separately.

## Run locally

Prerequisites:

- Jac 0.34.7
- Icarus Verilog 13+

On macOS:

```bash
brew install icarus-verilog
jac install
jac start --dev main.jac
```

Open [http://localhost:8000](http://localhost:8000).

## Verify

```bash
JAC_DATA_PATH="$(mktemp -d)" jac test jacverify/store.jac -v
.jac/venv/bin/python -m pytest tests/test_tool_adapter.py -q
JAC_DATA_PATH="$(mktemp -d)" jac check .
```

The temporary `JAC_DATA_PATH` keeps test state separate from the live demo graph. With
Jac 0.34.7 microservice mode, do not run `jac clean --data` against a stopped or
running demo and then reuse its service user database: the stale guest-root record can
point at a deleted graph anchor. Avoid `jac clean --all` immediately before Python
tests because it removes `.jac/venv`.

## Architecture

```text
Jac client
  → typed Jac endpoints
    → ProjectPlanner walker
      → project/action graph
    → StateExecutor walker
      → verification job/transition graph
        → allow-listed Python tool adapter
          → Icarus Verilog
          → immutable run artifacts
```

Important entrypoints:

- `main.jac` — full-stack entry.
- `jacverify/store.jac` — graph schema, scoring policy, walkers, FSM, endpoints.
- `jacverify/Dashboard.jac` — project and task views.
- `jacverify/tool_adapter.py` — deterministic, allow-listed EDA adapter.
- `demo/fifo/` — specification, buggy/fixed RTL, smoke and wraparound testbenches.
- `runs/fifo-demo/tool_evidence.json` — generated evidence manifest.

## Scope and honesty

- Module A uses an executable local Icarus Verilog flow.
- Modules B/C, project budget, milestone, and aggregate failure counts are demo scenario inputs.
- The fixed RTL is a pre-approved patch fixture, not an autonomous production code change.
- The LLM/model layer never declares verification success; pass/fail states come from deterministic tools and Jac guards.

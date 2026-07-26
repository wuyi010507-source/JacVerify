"""Allow-listed curated-case tool adapter with explicit mock/live modes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

STATUS_PASSED = "PASSED"
STATUS_VERIFICATION_FAILED = "VERIFICATION_FAILED"
STATUS_TOOL_ERROR = "TOOL_ERROR"
STATUS_BUG_NOT_REPRODUCED = "BUG_NOT_REPRODUCED"
STATUS_NOT_RUN = "NOT_RUN"

MISMATCH_RE = re.compile(
    r"(WRAP_MISMATCH|ALU_MISMATCH|SHIFT_MISMATCH)\s+"
    r"expected=([0-9A-Fa-fxX]+)\s+observed=([0-9A-Fa-fxX]+)"
)
WRAP_MISMATCH_RE = MISMATCH_RE  # backward-compatible alias

_ACTIVE_CASE_ID = "fifo"


@dataclass(frozen=True)
class CaseConfig:
    case_id: str
    title: str
    description: str
    module_name: str
    demo_dir: str
    buggy_name: str
    fixed_name: str
    smoke_tb: str
    directed_tb: str
    spec_name: str
    accepted_filenames: tuple[str, ...]
    fail_tag: str
    pass_tag: str
    mock_fail_stdout: str
    mock_pass_stdout: str


CASE_CONFIGS: dict[str, CaseConfig] = {
    "fifo": CaseConfig(
        case_id="fifo",
        title="FIFO wraparound",
        description=(
            "Module-level FIFO with a planted write-pointer wrap bug."
        ),
        module_name="fifo",
        demo_dir="fifo",
        buggy_name="fifo_buggy.sv",
        fixed_name="fifo_fixed.sv",
        smoke_tb="tb_smoke.sv",
        directed_tb="tb_wrap.sv",
        spec_name="fifo_spec.md",
        accepted_filenames=("fifo_buggy.sv", "fifo.sv"),
        fail_tag="WRAP_MISMATCH",
        pass_tag="WRAP_TEST_PASS",
        mock_fail_stdout="WRAP_MISMATCH expected=55 observed=33\n",
        mock_pass_stdout="WRAP_TEST_PASS\n",
    ),
    "alu": CaseConfig(
        case_id="alu",
        title="ALU subtract opcode",
        description=(
            "Small ALU where SUB incorrectly adds instead of subtracts."
        ),
        module_name="alu",
        demo_dir="alu",
        buggy_name="alu_buggy.sv",
        fixed_name="alu_fixed.sv",
        smoke_tb="tb_smoke.sv",
        directed_tb="tb_directed.sv",
        spec_name="alu_spec.md",
        accepted_filenames=("alu_buggy.sv", "alu.sv"),
        fail_tag="ALU_MISMATCH",
        pass_tag="ALU_TEST_PASS",
        mock_fail_stdout="ALU_MISMATCH expected=05 observed=0b\n",
        mock_pass_stdout="ALU_TEST_PASS\n",
    ),
    "shift_reg": CaseConfig(
        case_id="shift_reg",
        title="Shift-register direction",
        description=(
            "Shift register that shifts left instead of the specified right shift."
        ),
        module_name="shift_reg",
        demo_dir="shift_reg",
        buggy_name="shift_reg_buggy.sv",
        fixed_name="shift_reg_fixed.sv",
        smoke_tb="tb_smoke.sv",
        directed_tb="tb_directed.sv",
        spec_name="shift_reg_spec.md",
        accepted_filenames=("shift_reg_buggy.sv", "shift_reg.sv"),
        fail_tag="SHIFT_MISMATCH",
        pass_tag="SHIFT_TEST_PASS",
        mock_fail_stdout="SHIFT_MISMATCH expected=40 observed=00\n",
        mock_pass_stdout="SHIFT_TEST_PASS\n",
    ),
}


def set_active_case(case_id: str) -> str:
    global _ACTIVE_CASE_ID
    if case_id not in CASE_CONFIGS:
        raise ValueError(f"Unknown curated case_id: {case_id}")
    _ACTIVE_CASE_ID = case_id
    return case_id


def get_active_case_id() -> str:
    return _ACTIVE_CASE_ID


def active_case() -> CaseConfig:
    return CASE_CONFIGS[_ACTIVE_CASE_ID]


@dataclass(frozen=True)
class ToolResult:
    tool: str
    mode: str
    status: str
    exit_code: int | None
    command: list[str]
    duration_ms: int
    stdout: str
    stderr: str
    artifacts: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FailureEvidence:
    kind: str
    expected: str | None
    observed: str | None
    cycle: int | None
    raw_stdout: str
    source_result: ToolResult


@dataclass(frozen=True)
class RequirementItem:
    req_id: str
    text: str


@dataclass(frozen=True)
class SpecLoadResult:
    requirement_count: int
    spec_path: str
    requirements: list[RequirementItem]
    module_path: str
    module_name: str
    mode: str


# Backward-compatible aliases used by older tests during migration.
ToolRun = ToolResult


@dataclass(frozen=True)
class FifoSuiteEvidence:
    """Legacy batch suite wrapper; prefer per-stage ToolResult APIs."""

    spec_requirement_count: int
    spec_path: str
    lint: ToolResult
    smoke: ToolResult
    failing_regression: ToolResult
    patched_reverify: ToolResult


def tools_mode() -> str:
    return "mock" if os.environ.get("JACVERIFY_MOCK_TOOLS", "") == "1" else "live"


def llm_mode() -> str:
    return "mock" if os.environ.get("JACVERIFY_MOCK_LLM", "1") == "1" else "live"


def _tool_error(
    *,
    tool: str,
    mode: str,
    command: list[str],
    duration_ms: int,
    stdout: str = "",
    stderr: str = "",
    artifacts: list[str] | None = None,
    diagnostics: dict[str, Any] | None = None,
    exit_code: int | None = None,
) -> ToolResult:
    return ToolResult(
        tool=tool,
        mode=mode,
        status=STATUS_TOOL_ERROR,
        exit_code=exit_code,
        command=command,
        duration_ms=duration_ms,
        stdout=stdout,
        stderr=stderr,
        artifacts=artifacts or [],
        diagnostics=diagnostics or {},
    )


def _case_paths(workspace_root: str, case: CaseConfig | None = None) -> dict[str, Path]:
    cfg = case or active_case()
    root = Path(workspace_root).resolve()
    case_dir = root / "demo" / cfg.demo_dir
    paths = {
        "root": root,
        "case_dir": case_dir,
        "buggy_rtl": case_dir / cfg.buggy_name,
        "fixed_rtl": case_dir / cfg.fixed_name,
        "smoke_tb": case_dir / cfg.smoke_tb,
        "wrap_tb": case_dir / cfg.directed_tb,
        "spec_path": case_dir / cfg.spec_name,
    }
    for key in ("buggy_rtl", "fixed_rtl", "smoke_tb", "wrap_tb", "spec_path"):
        path = paths[key]
        if not path.is_file() or case_dir not in path.parents:
            raise FileNotFoundError(
                f"Demo input missing or outside allow-list: {path}"
            )
    return paths


def _fifo_paths(workspace_root: str) -> dict[str, Path]:
    return _case_paths(workspace_root, CASE_CONFIGS["fifo"])


def load_spec(workspace_root: str) -> SpecLoadResult:
    cfg = active_case()
    paths = _case_paths(workspace_root, cfg)
    requirements: list[RequirementItem] = []
    for line in paths["spec_path"].read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("- REQ-"):
            continue
        body = stripped[2:].strip()
        req_id, _, text = body.partition(":")
        requirements.append(
            RequirementItem(
                req_id=req_id.strip(),
                text=text.strip() or body,
            )
        )
    if len(requirements) != 5:
        raise ValueError(
            f"{cfg.case_id} specification must contain exactly five requirements"
        )
    return SpecLoadResult(
        requirement_count=len(requirements),
        spec_path=str(paths["spec_path"]),
        requirements=requirements,
        module_path=str(paths["buggy_rtl"]),
        module_name=cfg.module_name,
        mode=tools_mode(),
    )


def parse_failure_evidence(result: ToolResult) -> FailureEvidence | None:
    match = MISMATCH_RE.search(result.stdout or "")
    if not match:
        return None
    return FailureEvidence(
        kind=match.group(1),
        expected=match.group(2),
        observed=match.group(3),
        cycle=None,
        raw_stdout=result.stdout,
        source_result=result,
    )


def rebuild_tool_result(
    *,
    tool: str,
    mode: str,
    status: str,
    exit_code: int,
    stdout: str,
    stderr: str = "",
    duration_ms: int = 0,
) -> ToolResult:
    return ToolResult(
        tool=tool,
        mode=mode,
        status=status,
        exit_code=exit_code,
        command=[],
        duration_ms=duration_ms,
        stdout=stdout,
        stderr=stderr,
        artifacts=[],
        diagnostics={},
    )


def parse_failure_from_stored(
    *,
    tool: str,
    mode: str,
    status: str,
    exit_code: int,
    stdout: str,
) -> FailureEvidence | None:
    result = rebuild_tool_result(
        tool=tool,
        mode=mode,
        status=status,
        exit_code=exit_code,
        stdout=stdout,
    )
    return parse_failure_evidence(result)


def _mock_compile() -> ToolResult:
    cfg = active_case()
    return ToolResult(
        tool="iverilog",
        mode="mock",
        status=STATUS_PASSED,
        exit_code=0,
        command=[
            "mock:iverilog",
            "-g2012",
            "-tnull",
            "-s",
            cfg.module_name,
            cfg.buggy_name,
        ],
        duration_ms=1,
        stdout="mock lint/compile ok\n",
        stderr="",
        artifacts=[],
        diagnostics={"stage": "compile", "case_id": cfg.case_id},
    )


def _mock_smoke() -> ToolResult:
    cfg = active_case()
    return ToolResult(
        tool="vvp",
        mode="mock",
        status=STATUS_PASSED,
        exit_code=0,
        command=["mock:vvp", "smoke.vvp"],
        duration_ms=1,
        stdout="SMOKE_TEST_PASS\n",
        stderr="",
        artifacts=["mock:smoke.vvp"],
        diagnostics={"stage": "smoke", "test": "tb_smoke", "case_id": cfg.case_id},
    )


def _mock_regression(*, reproduce_bug: bool = True) -> ToolResult:
    cfg = active_case()
    if reproduce_bug:
        return ToolResult(
            tool="vvp",
            mode="mock",
            status=STATUS_VERIFICATION_FAILED,
            exit_code=1,
            command=["mock:vvp", "directed_regression.vvp"],
            duration_ms=2,
            stdout=cfg.mock_fail_stdout,
            stderr="",
            artifacts=["mock:directed_regression.vvp"],
            diagnostics={
                "stage": "directed_regression",
                "test": cfg.directed_tb,
                "case_id": cfg.case_id,
            },
        )
    return ToolResult(
        tool="vvp",
        mode="mock",
        status=STATUS_BUG_NOT_REPRODUCED,
        exit_code=0,
        command=["mock:vvp", "directed_regression.vvp"],
        duration_ms=2,
        stdout=cfg.mock_pass_stdout,
        stderr="",
        artifacts=["mock:directed_regression.vvp"],
        diagnostics={
            "stage": "directed_regression",
            "test": cfg.directed_tb,
            "case_id": cfg.case_id,
        },
    )


def _mock_reverify(*, pass_result: bool = True) -> ToolResult:
    cfg = active_case()
    candidate = f"demo/{cfg.demo_dir}/{cfg.fixed_name}"
    if pass_result:
        return ToolResult(
            tool="vvp",
            mode="mock",
            status=STATUS_PASSED,
            exit_code=0,
            command=["mock:vvp", "patched_reverify.vvp"],
            duration_ms=2,
            stdout=cfg.mock_pass_stdout,
            stderr="",
            artifacts=["mock:patched_reverify.vvp"],
            diagnostics={
                "stage": "patched_reverify",
                "candidate": candidate,
                "candidate_kind": "reviewed_fixture",
                "case_id": cfg.case_id,
            },
        )
    return ToolResult(
        tool="vvp",
        mode="mock",
        status=STATUS_VERIFICATION_FAILED,
        exit_code=1,
        command=["mock:vvp", "patched_reverify.vvp"],
        duration_ms=2,
        stdout=cfg.mock_fail_stdout,
        stderr="",
        artifacts=["mock:patched_reverify.vvp"],
        diagnostics={
            "stage": "patched_reverify",
            "candidate": candidate,
            "candidate_kind": "reviewed_fixture",
            "case_id": cfg.case_id,
        },
    )


def _execute(
    *,
    tool: str,
    command: list[str],
    cwd: Path,
    artifacts: list[Path] | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> ToolResult:
    mode = "live"
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except FileNotFoundError as exc:
        return _tool_error(
            tool=tool,
            mode=mode,
            command=command,
            duration_ms=int((time.perf_counter() - started) * 1000),
            stderr=str(exc),
            diagnostics={**(diagnostics or {}), "error": "executable_not_found"},
        )
    except subprocess.TimeoutExpired as exc:
        return _tool_error(
            tool=tool,
            mode=mode,
            command=command,
            duration_ms=int((time.perf_counter() - started) * 1000),
            stdout=exc.stdout or "",
            stderr=exc.stderr or "timeout",
            diagnostics={**(diagnostics or {}), "error": "timeout"},
        )
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ToolResult(
        tool=tool,
        mode=mode,
        status=STATUS_PASSED if completed.returncode == 0 else STATUS_TOOL_ERROR,
        exit_code=completed.returncode,
        command=command,
        duration_ms=duration_ms,
        stdout=completed.stdout,
        stderr=completed.stderr,
        artifacts=[str(path) for path in artifacts or []],
        diagnostics=diagnostics or {},
    )


def _ensure_output_dir(output_dir: str) -> Path:
    artifacts = Path(output_dir).resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    return artifacts


def lint_compile(workspace_root: str, output_dir: str) -> ToolResult:
    cfg = active_case()
    if tools_mode() == "mock":
        return _mock_compile()
    if shutil.which("iverilog") is None:
        return _tool_error(
            tool="iverilog",
            mode="live",
            command=["iverilog"],
            duration_ms=0,
            stderr="iverilog not found on PATH",
            diagnostics={"error": "executable_not_found", "stage": "compile"},
        )
    paths = _case_paths(workspace_root, cfg)
    artifacts = _ensure_output_dir(output_dir)
    result = _execute(
        tool="iverilog",
        command=[
            "iverilog",
            "-g2012",
            "-tnull",
            "-s",
            cfg.module_name,
            str(paths["buggy_rtl"]),
        ],
        cwd=artifacts,
        diagnostics={"stage": "compile", "case_id": cfg.case_id},
    )
    if result.status == STATUS_PASSED:
        return result
    if result.status == STATUS_TOOL_ERROR:
        return result
    return ToolResult(
        tool=result.tool,
        mode=result.mode,
        status=STATUS_TOOL_ERROR,
        exit_code=result.exit_code,
        command=result.command,
        duration_ms=result.duration_ms,
        stdout=result.stdout,
        stderr=result.stderr,
        artifacts=result.artifacts,
        diagnostics={**result.diagnostics, "stage": "compile"},
    )


def _compile_and_simulate(
    *,
    stage: str,
    rtl: Path,
    testbench: Path,
    output_dir: Path,
) -> ToolResult:
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        return _tool_error(
            tool="iverilog",
            mode="live",
            command=["iverilog", "vvp"],
            duration_ms=0,
            stderr="iverilog/vvp not found on PATH",
            diagnostics={"error": "executable_not_found", "stage": stage},
        )
    binary = output_dir / f"{stage}.vvp"
    compile_result = _execute(
        tool="iverilog",
        command=[
            "iverilog",
            "-g2012",
            "-s",
            testbench.stem,
            "-o",
            str(binary),
            str(rtl),
            str(testbench),
        ],
        cwd=output_dir,
        artifacts=[binary],
        diagnostics={"stage": f"{stage}_compile"},
    )
    if compile_result.status != STATUS_PASSED:
        return ToolResult(
            tool=compile_result.tool,
            mode=compile_result.mode,
            status=STATUS_TOOL_ERROR,
            exit_code=compile_result.exit_code,
            command=compile_result.command,
            duration_ms=compile_result.duration_ms,
            stdout=compile_result.stdout,
            stderr=compile_result.stderr,
            artifacts=compile_result.artifacts,
            diagnostics={**compile_result.diagnostics, "stage": stage},
        )
    sim = _execute(
        tool="vvp",
        command=["vvp", str(binary)],
        cwd=output_dir,
        artifacts=[binary],
        diagnostics={"stage": stage, "test": testbench.stem},
    )
    return ToolResult(
        tool=sim.tool,
        mode=sim.mode,
        status=sim.status if sim.status == STATUS_PASSED else STATUS_TOOL_ERROR,
        exit_code=sim.exit_code,
        command=sim.command,
        duration_ms=compile_result.duration_ms + sim.duration_ms,
        stdout=sim.stdout,
        stderr=sim.stderr,
        artifacts=sim.artifacts,
        diagnostics=sim.diagnostics,
    )


def run_smoke(workspace_root: str, output_dir: str) -> ToolResult:
    cfg = active_case()
    if tools_mode() == "mock":
        return _mock_smoke()
    paths = _case_paths(workspace_root, cfg)
    artifacts = _ensure_output_dir(output_dir)
    result = _compile_and_simulate(
        stage="smoke",
        rtl=paths["buggy_rtl"],
        testbench=paths["smoke_tb"],
        output_dir=artifacts,
    )
    if result.status == STATUS_PASSED and "SMOKE_TEST_PASS" in result.stdout:
        return result
    if result.status == STATUS_TOOL_ERROR:
        return result
    return ToolResult(
        tool=result.tool,
        mode=result.mode,
        status=STATUS_VERIFICATION_FAILED,
        exit_code=result.exit_code,
        command=result.command,
        duration_ms=result.duration_ms,
        stdout=result.stdout,
        stderr=result.stderr,
        artifacts=result.artifacts,
        diagnostics={**result.diagnostics, "stage": "smoke"},
    )


def run_wrap_regression(workspace_root: str, output_dir: str) -> ToolResult:
    cfg = active_case()
    if tools_mode() == "mock":
        force = os.environ.get("JACVERIFY_FORCE_BUG_NOT_REPRODUCED", "")
        return _mock_regression(reproduce_bug=force != "1")
    paths = _case_paths(workspace_root, cfg)
    artifacts = _ensure_output_dir(output_dir)
    result = _compile_and_simulate(
        stage="directed_regression",
        rtl=paths["buggy_rtl"],
        testbench=paths["wrap_tb"],
        output_dir=artifacts,
    )
    if result.status == STATUS_TOOL_ERROR and result.diagnostics.get("error"):
        return result
    if cfg.fail_tag in result.stdout:
        return ToolResult(
            tool=result.tool,
            mode=result.mode,
            status=STATUS_VERIFICATION_FAILED,
            exit_code=result.exit_code if result.exit_code is not None else 1,
            command=result.command,
            duration_ms=result.duration_ms,
            stdout=result.stdout,
            stderr=result.stderr,
            artifacts=result.artifacts,
            diagnostics={
                **result.diagnostics,
                "stage": "directed_regression",
                "case_id": cfg.case_id,
            },
        )
    if cfg.pass_tag in result.stdout or result.exit_code == 0:
        return ToolResult(
            tool=result.tool,
            mode=result.mode,
            status=STATUS_BUG_NOT_REPRODUCED,
            exit_code=result.exit_code,
            command=result.command,
            duration_ms=result.duration_ms,
            stdout=result.stdout,
            stderr=result.stderr,
            artifacts=result.artifacts,
            diagnostics={
                **result.diagnostics,
                "stage": "directed_regression",
                "case_id": cfg.case_id,
            },
        )
    return ToolResult(
        tool=result.tool,
        mode=result.mode,
        status=STATUS_TOOL_ERROR,
        exit_code=result.exit_code,
        command=result.command,
        duration_ms=result.duration_ms,
        stdout=result.stdout,
        stderr=result.stderr,
        artifacts=result.artifacts,
        diagnostics={
            **result.diagnostics,
            "stage": "directed_regression",
            "error": "malformed_output",
            "case_id": cfg.case_id,
        },
    )


def run_reverify(workspace_root: str, output_dir: str) -> ToolResult:
    cfg = active_case()
    if tools_mode() == "mock":
        force_fail = os.environ.get("JACVERIFY_FORCE_REVERIFY_FAIL", "")
        return _mock_reverify(pass_result=force_fail != "1")
    paths = _case_paths(workspace_root, cfg)
    artifacts = _ensure_output_dir(output_dir)
    result = _compile_and_simulate(
        stage="patched_reverify",
        rtl=paths["fixed_rtl"],
        testbench=paths["wrap_tb"],
        output_dir=artifacts,
    )
    diagnostics = {
        **result.diagnostics,
        "stage": "patched_reverify",
        "candidate": str(paths["fixed_rtl"]),
        "candidate_kind": "reviewed_fixture",
        "case_id": cfg.case_id,
    }
    if result.status == STATUS_PASSED and cfg.pass_tag in result.stdout:
        return ToolResult(
            tool=result.tool,
            mode=result.mode,
            status=STATUS_PASSED,
            exit_code=result.exit_code,
            command=result.command,
            duration_ms=result.duration_ms,
            stdout=result.stdout,
            stderr=result.stderr,
            artifacts=result.artifacts,
            diagnostics=diagnostics,
        )
    if cfg.fail_tag in result.stdout:
        return ToolResult(
            tool=result.tool,
            mode=result.mode,
            status=STATUS_VERIFICATION_FAILED,
            exit_code=result.exit_code,
            command=result.command,
            duration_ms=result.duration_ms,
            stdout=result.stdout,
            stderr=result.stderr,
            artifacts=result.artifacts,
            diagnostics=diagnostics,
        )
    return ToolResult(
        tool=result.tool,
        mode=result.mode,
        status=STATUS_TOOL_ERROR,
        exit_code=result.exit_code,
        command=result.command,
        duration_ms=result.duration_ms,
        stdout=result.stdout,
        stderr=result.stderr,
        artifacts=result.artifacts,
        diagnostics={**diagnostics, "error": "malformed_or_failed_reverify"},
    )


@dataclass(frozen=True)
class HypothesisDraft:
    rank: int
    claim: str
    confidence: float
    next_action: str


@dataclass(frozen=True)
class ArtifactDraft:
    kind: str
    description: str
    candidate_path: str
    candidate_label: str
    hypothesis_claim: str
    notes: str


def rank_hypotheses_mock(failure: FailureEvidence) -> list[HypothesisDraft]:
    """Deterministic diagnosis aligned with the active curated case's planted bug."""
    cfg = active_case()
    expected = failure.expected or "?"
    observed = failure.observed or "?"
    if cfg.case_id == "alu":
        return [
            HypothesisDraft(
                rank=1,
                claim=(
                    "SUB opcode incorrectly computes a+b instead of a-b "
                    f"(expected={expected}, observed={observed})."
                ),
                confidence=0.91,
                next_action=(
                    "Apply reviewed ALU SUB fix fixture and reverify."
                ),
            ),
            HypothesisDraft(
                rank=2,
                claim="ADD opcode wraps incorrectly on overflow.",
                confidence=0.16,
                next_action="Compare ADD vectors against wrap semantics.",
            ),
            HypothesisDraft(
                rank=3,
                claim="Registered result updates one cycle late relative to opcode.",
                confidence=0.08,
                next_action="Inspect always_ff sampling against tb_directed timing.",
            ),
        ]
    if cfg.case_id == "shift_reg":
        return [
            HypothesisDraft(
                rank=1,
                claim=(
                    "Shift direction is inverted: register shifts left instead of "
                    f"right (expected={expected}, observed={observed})."
                ),
                confidence=0.91,
                next_action=(
                    "Apply reviewed right-shift fix fixture and reverify."
                ),
            ),
            HypothesisDraft(
                rank=2,
                claim="serial_in is wired into the LSB instead of the MSB on shift.",
                confidence=0.17,
                next_action="Trace serial_in concatenation in the shift branch.",
            ),
            HypothesisDraft(
                rank=3,
                claim="load path corrupts q before the directed shift sequence.",
                confidence=0.07,
                next_action="Check load vs shift priority against the smoke test.",
            ),
        ]
    return [
        HypothesisDraft(
            rank=1,
            claim=(
                "Write pointer wraps to 1 instead of 0 after DEPTH-1, corrupting "
                f"FIFO order (expected={expected}, observed={observed})."
            ),
            confidence=0.91,
            next_action=(
                "Apply reviewed write-pointer wrap fix fixture and reverify."
            ),
        ),
        HypothesisDraft(
            rank=2,
            claim="Read pointer wrap is incorrect after DEPTH-1.",
            confidence=0.18,
            next_action="Inspect read_ptr update against tb_wrap sequence.",
        ),
        HypothesisDraft(
            rank=3,
            claim="Occupancy counter drifts on concurrent accepted read/write.",
            confidence=0.09,
            next_action="Check count case statement under simultaneous enables.",
        ),
    ]


def generate_artifact_mock(
    hypothesis: HypothesisDraft,
    module_name: str,
) -> ArtifactDraft:
    cfg = active_case()
    candidate_path = f"demo/{cfg.demo_dir}/{cfg.fixed_name}"
    return ArtifactDraft(
        kind="reviewed_candidate_fixture",
        description=(
            f"Directed reverify artifact for module `{module_name}`: "
            f"apply pre-reviewed candidate `{candidate_path}`, then rerun "
            f"{cfg.directed_tb}."
        ),
        candidate_path=candidate_path,
        candidate_label=f"reviewed_fixture:{cfg.fixed_name}",
        hypothesis_claim=hypothesis.claim,
        notes=(
            "Candidate is a pre-reviewed fixture, not an LLM-authored RTL patch."
        ),
    )


def rank_hypotheses(failure: FailureEvidence) -> list[HypothesisDraft]:
    if llm_mode() == "mock":
        return rank_hypotheses_mock(failure)
    raise RuntimeError(
        "Live LLM mode requested (JACVERIFY_MOCK_LLM!=1) but no live byllm "
        "backend is configured for this hackathon build. Set JACVERIFY_MOCK_LLM=1."
    )


def generate_artifact(
    hypothesis: HypothesisDraft,
    module_name: str,
) -> ArtifactDraft:
    if llm_mode() == "mock":
        return generate_artifact_mock(hypothesis, module_name)
    raise RuntimeError(
        "Live LLM mode requested (JACVERIFY_MOCK_LLM!=1) but no live byllm "
        "backend is configured for this hackathon build. Set JACVERIFY_MOCK_LLM=1."
    )


def make_failure_evidence(
    *,
    kind: str,
    expected: str,
    observed: str,
    raw_stdout: str,
    source_result: ToolResult,
    cycle: int | None = None,
) -> FailureEvidence:
    return FailureEvidence(
        kind=kind,
        expected=expected or None,
        observed=observed or None,
        cycle=cycle,
        raw_stdout=raw_stdout,
        source_result=source_result,
    )


def make_hypothesis_draft(
    rank: int,
    claim: str,
    confidence: float,
    next_action: str,
) -> HypothesisDraft:
    return HypothesisDraft(
        rank=rank,
        claim=claim,
        confidence=confidence,
        next_action=next_action,
    )


def fresh_run_id(prefix: str = "fifo-run") -> str:
    return f"{prefix}-{int(time.time() * 1000)}"


def normalize_source(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"


def source_fingerprint(text: str) -> str:
    return hashlib.sha256(normalize_source(text).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CuratedCase:
    case_id: str
    title: str
    description: str
    buggy_relpath: str
    accepted_filenames: tuple[str, ...]


@dataclass(frozen=True)
class UploadMatch:
    accepted: bool
    case_id: str
    case_title: str
    message: str
    filename: str


CURATED_CASES: tuple[CuratedCase, ...] = tuple(
    CuratedCase(
        case_id=cfg.case_id,
        title=cfg.title,
        description=(
            f"{cfg.description} Hackathon demo uses a reviewed fix fixture "
            "for re-verification."
        ),
        buggy_relpath=f"demo/{cfg.demo_dir}/{cfg.buggy_name}",
        accepted_filenames=cfg.accepted_filenames,
    )
    for cfg in CASE_CONFIGS.values()
)


def list_curated_cases() -> list[dict[str, str]]:
    return [
        {
            "case_id": case.case_id,
            "title": case.title,
            "description": case.description,
            "buggy_relpath": case.buggy_relpath,
            "accepted_filenames": ", ".join(case.accepted_filenames),
        }
        for case in CURATED_CASES
    ]


def _case_buggy_text(workspace_root: str, case: CuratedCase) -> str:
    path = Path(workspace_root).resolve() / case.buggy_relpath
    if not path.is_file():
        raise FileNotFoundError(f"Curated case RTL missing: {path}")
    return path.read_text(encoding="utf-8")


def identify_uploaded_case(
    workspace_root: str,
    filename: str,
    content: str,
) -> UploadMatch:
    """Match an uploaded design against curated hackathon cases.

    Upload UX is real; execution remains allow-listed to prepared cases.
    """
    basename = Path(filename or "").name.strip() or "upload.sv"
    if not content or not content.strip():
        return UploadMatch(
            accepted=False,
            case_id="",
            case_title="",
            message="Upload is empty. Choose an RTL design file to continue.",
            filename=basename,
        )

    upload_fp = source_fingerprint(content)
    for case in CURATED_CASES:
        try:
            curated_fp = source_fingerprint(_case_buggy_text(workspace_root, case))
        except FileNotFoundError:
            continue
        if upload_fp == curated_fp:
            return UploadMatch(
                accepted=True,
                case_id=case.case_id,
                case_title=case.title,
                message=(
                    f"Matched curated case `{case.title}` from upload "
                    f"`{basename}`. Ready to run the verification loop."
                ),
                filename=basename,
            )

    known = ", ".join(case.buggy_relpath for case in CURATED_CASES)
    return UploadMatch(
        accepted=False,
        case_id="",
        case_title="",
        message=(
            "This upload is not one of today's curated demo cases. "
            "JacVerify's upload path is enabled, but the hackathon runtime "
            f"only executes prepared designs ({known}). "
            "Try uploading demo/fifo/fifo_buggy.sv, demo/alu/alu_buggy.sv, "
            "or demo/shift_reg/shift_reg_buggy.sv."
        ),
        filename=basename,
    )


def read_text_file(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def load_curated_case_upload(
    workspace_root: str,
    case_id: str = "fifo",
) -> UploadMatch:
    """Server-side helper: treat a curated case as if the user uploaded it."""
    for case in CURATED_CASES:
        if case.case_id != case_id:
            continue
        text = _case_buggy_text(workspace_root, case)
        return identify_uploaded_case(
            workspace_root,
            Path(case.buggy_relpath).name,
            text,
        )
    return UploadMatch(
        accepted=False,
        case_id="",
        case_title="",
        message=f"Unknown curated case_id: {case_id}",
        filename="",
    )


def tool_result_to_dict(result: ToolResult) -> dict[str, Any]:
    return asdict(result)


def write_stage_manifest(output_dir: str, name: str, payload: dict[str, Any]) -> str:
    artifacts = _ensure_output_dir(output_dir)
    path = artifacts / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(path)


def run_fifo_suite(workspace_root: str, output_dir: str) -> FifoSuiteEvidence:
    """Legacy batch helper used by older tests; not the walker orchestration path."""
    spec = load_spec(workspace_root)
    lint = lint_compile(workspace_root, output_dir)
    smoke = run_smoke(workspace_root, output_dir)
    failing_regression = run_wrap_regression(workspace_root, output_dir)
    patched_reverify = run_reverify(workspace_root, output_dir)
    evidence = FifoSuiteEvidence(
        spec_requirement_count=spec.requirement_count,
        spec_path=spec.spec_path,
        lint=lint,
        smoke=smoke,
        failing_regression=failing_regression,
        patched_reverify=patched_reverify,
    )
    write_stage_manifest(output_dir, "tool_evidence", asdict(evidence))
    return evidence

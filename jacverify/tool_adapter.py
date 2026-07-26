"""Allow-listed curated-case tool adapter with explicit mock/live modes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
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
COVERAGE_RE = re.compile(
    r"JACVERIFY_COVERAGE\s+code=([0-9]+(?:\.[0-9]+)?)"
    r"\s+functional=([0-9]+(?:\.[0-9]+)?)"
)
MODULE_RE = re.compile(r"\bmodule\s+([A-Za-z_][A-Za-z0-9_$]*)\b")


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


@dataclass(frozen=True)
class CoverageResult:
    available: bool
    code_coverage: float
    functional_coverage: float
    source: str


@dataclass(frozen=True)
class UploadedInputPaths:
    design_path: str
    spec_path: str
    test_path: str
    design_module: str
    test_module: str


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


def llm_backend() -> str:
    """Select the live inference adapter without affecting deterministic mock mode."""
    return os.environ.get("JACVERIFY_LLM_BACKEND", "firecrawl").strip().lower()


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
    paths = _fifo_paths(workspace_root)
    return load_uploaded_spec(
        str(paths["spec_path"]),
        str(paths["buggy_rtl"]),
        "fifo",
    )


def load_uploaded_spec(
    spec_path: str,
    module_path: str,
    module_name: str,
) -> SpecLoadResult:
    """Load requirements from an uploaded spec, with a plain-text fallback."""
    path = Path(spec_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Uploaded specification is missing: {path}")
    spec_text = path.read_text(encoding="utf-8")
    requirements: list[RequirementItem] = []
    for line in spec_text.splitlines():
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
    if not requirements:
        fallback = " ".join(
            line.strip().lstrip("#").strip()
            for line in spec_text.splitlines()
            if line.strip()
        )
        if not fallback:
            raise ValueError("Uploaded specification is empty")
        requirements.append(
            RequirementItem(
                req_id="REQ-SPEC",
                text=fallback[:1000],
            )
        )
    return SpecLoadResult(
        requirement_count=len(requirements),
        spec_path=str(path),
        requirements=requirements,
        module_path=module_path,
        module_name=module_name,
        mode=tools_mode(),
    )


def parse_failure_evidence(result: ToolResult) -> FailureEvidence | None:
    match = WRAP_MISMATCH_RE.search(result.stdout or "")
    if match:
        return FailureEvidence(
            kind="WRAP_MISMATCH",
            expected=match.group(1),
            observed=match.group(2),
            cycle=None,
            raw_stdout=result.stdout,
            source_result=result,
        )
    if result.status == STATUS_VERIFICATION_FAILED:
        return FailureEvidence(
            kind="TEST_FAILURE",
            expected=None,
            observed=None,
            cycle=None,
            raw_stdout=result.stdout or result.stderr,
            source_result=result,
        )
    return None


def coverage_from_result(result: ToolResult) -> CoverageResult:
    matches = list(COVERAGE_RE.finditer(result.stdout or ""))
    if not matches:
        return CoverageResult(
            available=False,
            code_coverage=0.0,
            functional_coverage=0.0,
            source="not_reported",
        )
    match = matches[-1]
    return CoverageResult(
        available=True,
        code_coverage=min(100.0, max(0.0, float(match.group(1)))),
        functional_coverage=min(100.0, max(0.0, float(match.group(2)))),
        source=(
            "mock:testbench_marker"
            if result.mode == "mock"
            else "testbench_marker"
        ),
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
        stdout = (
            "JACVERIFY_COVERAGE code=72.5 functional=66.7\n"
            "WRAP_MISMATCH expected=55 observed=33\n"
        )
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
        stdout=(
            "JACVERIFY_COVERAGE code=88.0 functional=100.0\n"
            "WRAP_TEST_PASS\n"
        ),
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
            stdout=(
                "JACVERIFY_COVERAGE code=91.0 functional=100.0\n"
                "WRAP_TEST_PASS\n"
            ),
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
        stdout=(
            "JACVERIFY_COVERAGE code=78.0 functional=66.7\n"
            "WRAP_MISMATCH expected=55 observed=33\n"
        ),
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


def _safe_upload_name(filename: str, fallback: str) -> str:
    basename = Path(filename or "").name.strip()
    if not basename or basename in {".", ".."}:
        return fallback
    return re.sub(r"[^A-Za-z0-9_.-]", "_", basename)


def _module_name(source: str, label: str) -> str:
    match = MODULE_RE.search(source)
    if not match:
        raise ValueError(f"{label} does not declare a SystemVerilog module")
    return match.group(1)


def materialize_uploaded_inputs(
    workspace_root: str,
    output_dir: str,
    design_filename: str,
    design_content: str,
    spec_filename: str,
    spec_content: str,
) -> UploadedInputPaths:
    """Write design/spec inputs and inject the prototype generated testbench."""
    inputs_dir = _ensure_output_dir(output_dir) / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    design_name = _safe_upload_name(design_filename, "design.sv")
    spec_name = _safe_upload_name(spec_filename, "spec.md")
    test_name = "generated_tb_wrap.sv"
    design_path = inputs_dir / design_name
    spec_path = inputs_dir / spec_name
    test_path = inputs_dir / test_name
    normalized_design = normalize_source(design_content)
    normalized_spec = normalize_source(spec_content)
    normalized_test = normalize_source(
        _fifo_paths(workspace_root)["wrap_tb"].read_text(encoding="utf-8")
    )
    design_path.write_text(normalized_design, encoding="utf-8")
    spec_path.write_text(normalized_spec, encoding="utf-8")
    test_path.write_text(normalized_test, encoding="utf-8")
    return UploadedInputPaths(
        design_path=str(design_path),
        spec_path=str(spec_path),
        test_path=str(test_path),
        design_module=_module_name(normalized_design, "Uploaded design"),
        test_module=_module_name(normalized_test, "Generated testbench"),
    )


def lint_compile(
    workspace_root: str,
    output_dir: str,
    design_path: str = "",
    test_path: str = "",
    top_module: str = "",
) -> ToolResult:
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
    rtl = (
        Path(design_path).resolve()
        if design_path
        else _fifo_paths(workspace_root)["buggy_rtl"]
    )
    testbench = Path(test_path).resolve() if test_path else None
    artifacts = _ensure_output_dir(output_dir)
    command = ["iverilog", "-g2012", "-tnull"]
    if top_module:
        command.extend(["-s", top_module])
    else:
        command.extend(["-s", "fifo"])
    command.append(str(rtl))
    if testbench is not None:
        command.append(str(testbench))
    result = _execute(
        tool="iverilog",
        command=command,
        cwd=artifacts,
        diagnostics={
            "stage": "compile",
            "design": str(rtl),
            "test": str(testbench) if testbench is not None else "",
            "top": top_module or "fifo",
        },
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
    top_module: str = "",
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
            top_module or testbench.stem,
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
    paths = _fifo_paths(workspace_root) if not candidate_path or not test_path else {}
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


def run_uploaded_test(
    workspace_root: str,
    output_dir: str,
    design_path: str,
    test_path: str,
) -> ToolResult:
    """Compile the uploaded design with the test generated for this run."""
    if tools_mode() == "mock":
        force = os.environ.get("JACVERIFY_FORCE_BUG_NOT_REPRODUCED", "")
        return _mock_regression(reproduce_bug=force != "1")
    artifacts = _ensure_output_dir(output_dir)
    result = _compile_and_simulate(
        stage="uploaded_test",
        rtl=Path(design_path).resolve(),
        testbench=Path(test_path).resolve(),
        output_dir=artifacts,
        top_module=_module_name(
            Path(test_path).read_text(encoding="utf-8"),
            "Uploaded testbench",
        ),
    )
    diagnostics = {
        **result.diagnostics,
        "stage": "uploaded_test",
        "design": design_path,
        "test": test_path,
    }
    if result.status == STATUS_PASSED and result.exit_code == 0:
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
    if result.diagnostics.get("error"):
        return result
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
        diagnostics=diagnostics,
    )


def run_reverify(
    workspace_root: str,
    output_dir: str,
    attempt: int = 1,
    test_path: str = "",
    candidate_path: str = "",
) -> ToolResult:
    if tools_mode() == "mock":
        sequence_raw = os.environ.get("JACVERIFY_REVERIFY_SEQUENCE", "").strip()
        if sequence_raw:
            sequence = [
                item.strip().upper()
                for item in sequence_raw.split(",")
                if item.strip()
            ]
            if not sequence:
                return _tool_error(
                    tool="mock:vvp",
                    mode="mock",
                    command=["mock:vvp", "patched_reverify.vvp"],
                    duration_ms=1,
                    stderr="JACVERIFY_REVERIFY_SEQUENCE is empty",
                    diagnostics={"stage": "patched_reverify", "attempt": attempt},
                )
            selected = sequence[min(max(attempt, 1) - 1, len(sequence) - 1)]
            if selected == STATUS_PASSED:
                return _mock_reverify(pass_result=True)
            if selected == STATUS_VERIFICATION_FAILED:
                return _mock_reverify(pass_result=False)
            if selected == STATUS_TOOL_ERROR:
                return _tool_error(
                    tool="mock:vvp",
                    mode="mock",
                    command=["mock:vvp", "patched_reverify.vvp"],
                    duration_ms=1,
                    stderr="mock reverify tool error",
                    diagnostics={"stage": "patched_reverify", "attempt": attempt},
                    exit_code=2,
                )
            return _tool_error(
                tool="mock:vvp",
                mode="mock",
                command=["mock:vvp", "patched_reverify.vvp"],
                duration_ms=1,
                stderr=f"unsupported mock reverify status: {selected}",
                diagnostics={"stage": "patched_reverify", "attempt": attempt},
            )
        force_fail = os.environ.get("JACVERIFY_FORCE_REVERIFY_FAIL", "")
        return _mock_reverify(pass_result=force_fail != "1")
    paths = _fifo_paths(workspace_root)
    candidate = (
        Path(candidate_path).resolve()
        if candidate_path and Path(candidate_path).is_absolute()
        else (
            (Path(workspace_root).resolve() / candidate_path).resolve()
            if candidate_path
            else paths["fixed_rtl"]
        )
    )
    testbench = Path(test_path).resolve() if test_path else paths["wrap_tb"]
    artifacts = _ensure_output_dir(output_dir)
    result = _compile_and_simulate(
        stage="patched_reverify",
        rtl=candidate,
        testbench=testbench,
        output_dir=artifacts,
        top_module=_module_name(
            testbench.read_text(encoding="utf-8"),
            "Uploaded testbench",
        ),
    )
    diagnostics = {
        **result.diagnostics,
        "stage": "patched_reverify",
        "candidate": str(candidate),
        "candidate_kind": "reviewed_fixture",
        "test": str(testbench),
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


def _firecrawl_agent(
    *,
    prompt: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    """Run one bounded Firecrawl Agent extraction and return its typed data."""
    api_key = os.environ.get("FIRECRAWL_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "FIRECRAWL_API_KEY is empty. Keep JACVERIFY_MOCK_LLM=1 or put a "
            "Firecrawl key in the local .env file."
        )

    base_url = os.environ.get(
        "FIRECRAWL_API_URL", "https://api.firecrawl.dev/v2"
    ).rstrip("/")
    model = os.environ.get("JACVERIFY_FIRECRAWL_MODEL", "spark-1-mini").strip()
    max_credits = int(os.environ.get("JACVERIFY_FIRECRAWL_MAX_CREDITS", "100"))
    timeout_seconds = int(
        os.environ.get("JACVERIFY_FIRECRAWL_TIMEOUT_SECONDS", "60")
    )
    poll_seconds = float(
        os.environ.get("JACVERIFY_FIRECRAWL_POLL_SECONDS", "2")
    )

    if model not in {"spark-1-mini", "spark-1-pro"}:
        raise RuntimeError(f"Unsupported Firecrawl Agent model: {model}")
    if not 1 <= max_credits <= 2500:
        raise RuntimeError("JACVERIFY_FIRECRAWL_MAX_CREDITS must be 1..2500")
    if not 5 <= timeout_seconds <= 300:
        raise RuntimeError("JACVERIFY_FIRECRAWL_TIMEOUT_SECONDS must be 5..300")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "JacVerify/0.1",
    }

    def request_json(
        url: str,
        *,
        method: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = (
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
            if payload is not None
            else None
        )
        request = urllib.request.Request(
            url,
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                decoded = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise RuntimeError(
                f"Firecrawl HTTP {exc.code}: {detail or exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Firecrawl connection failed: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError("Firecrawl returned invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise RuntimeError("Firecrawl returned a non-object response")
        return decoded

    started = request_json(
        f"{base_url}/agent",
        method="POST",
        payload={
            "prompt": prompt[:10000],
            "schema": schema,
            "maxCredits": max_credits,
            "model": model,
        },
    )
    job_id = started.get("id")
    if started.get("success") is not True or not isinstance(job_id, str):
        raise RuntimeError(
            f"Firecrawl did not start an agent job: {started.get('error', started)}"
        )

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status = request_json(f"{base_url}/agent/{job_id}", method="GET")
        state = status.get("status")
        if state == "completed":
            data = status.get("data")
            if not isinstance(data, dict):
                raise RuntimeError("Firecrawl completed without object data")
            return data
        if state == "failed":
            raise RuntimeError(
                f"Firecrawl agent failed: {status.get('error', 'unknown error')}"
            )
        if state != "processing":
            raise RuntimeError(f"Unexpected Firecrawl agent status: {state!r}")
        time.sleep(poll_seconds)

    raise RuntimeError(
        f"Firecrawl agent timed out after {timeout_seconds}s"
    )


def rank_hypotheses_firecrawl(
    failure: FailureEvidence,
) -> list[HypothesisDraft]:
    """Experimental use of Firecrawl Agent as a constrained RTL reasoner."""
    schema = {
        "type": "object",
        "properties": {
            "hypotheses": {
                "type": "array",
                "minItems": 3,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "rank": {"type": "integer", "minimum": 1, "maximum": 3},
                        "claim": {"type": "string"},
                        "confidence": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                        },
                        "next_action": {"type": "string"},
                    },
                    "required": [
                        "rank",
                        "claim",
                        "confidence",
                        "next_action",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["hypotheses"],
        "additionalProperties": False,
    }
    data = _firecrawl_agent(
        prompt=(
            "Do not browse the web. Use only the evidence below. Act as a "
            "conservative RTL verification engineer. Return exactly three "
            "distinct, falsifiable FIFO root-cause hypotheses. Never declare "
            "PASS and never invent waveform facts.\n\n"
            "Requirements:\n"
            "- Reset leaves the FIFO empty and write-ready.\n"
            "- Values preserve FIFO ordering.\n"
            "- Exactly DEPTH entries are accepted before full.\n"
            "- Empty reads do not advance read_ptr.\n"
            "- Simultaneous accepted read/write preserves occupancy.\n\n"
            f"Failure kind: {failure.kind}\n"
            f"Expected: {failure.expected or ''}\n"
            f"Observed: {failure.observed or ''}\n"
            f"Cycle: {failure.cycle if failure.cycle is not None else ''}\n"
            f"Simulator output:\n{failure.raw_stdout[-4000:]}"
        ),
        schema=schema,
    )
    items = data.get("hypotheses")
    if not isinstance(items, list) or len(items) != 3:
        raise RuntimeError("Firecrawl must return exactly three hypotheses")

    drafts: list[HypothesisDraft] = []
    seen_ranks: set[int] = set()
    for raw in items:
        if not isinstance(raw, dict):
            raise RuntimeError("Firecrawl returned a malformed hypothesis")
        rank = int(raw.get("rank", 0))
        confidence = float(raw.get("confidence", -1))
        claim = str(raw.get("claim", "")).strip()
        next_action = str(raw.get("next_action", "")).strip()
        if (
            rank not in {1, 2, 3}
            or rank in seen_ranks
            or not 0 <= confidence <= 1
            or not claim
            or not next_action
        ):
            raise RuntimeError("Firecrawl returned an invalid hypothesis")
        seen_ranks.add(rank)
        drafts.append(
            HypothesisDraft(
                rank=rank,
                claim=claim,
                confidence=confidence,
                next_action=next_action,
            )
        )
    return sorted(drafts, key=lambda item: item.rank)


def generate_artifact_firecrawl(
    hypothesis: HypothesisDraft,
    module_name: str,
) -> ArtifactDraft:
    """Ask Firecrawl for a plan while retaining a hard-coded reviewed path."""
    schema = {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": [
                    "directed_test",
                    "sva_assertion",
                    "reviewed_rtl_candidate",
                ],
            },
            "description": {"type": "string"},
            "verification_goal": {"type": "string"},
            "rationale": {"type": "string"},
        },
        "required": [
            "kind",
            "description",
            "verification_goal",
            "rationale",
        ],
        "additionalProperties": False,
    }
    data = _firecrawl_agent(
        prompt=(
            "Do not browse the web. Use only the hypothesis below. Propose one "
            "minimal FIFO verification artifact. Do not return code, paths, "
            "shell commands, or a PASS/FAIL verdict. Prefer a directed "
            "wraparound test or focused assertion.\n\n"
            f"Module: {module_name}\n"
            f"Hypothesis: {hypothesis.claim}\n"
            f"Confidence: {hypothesis.confidence}\n"
            f"Suggested action: {hypothesis.next_action}"
        ),
        schema=schema,
    )
    kind = str(data.get("kind", "")).strip()
    description = str(data.get("description", "")).strip()
    verification_goal = str(data.get("verification_goal", "")).strip()
    rationale = str(data.get("rationale", "")).strip()
    if (
        kind
        not in {"directed_test", "sva_assertion", "reviewed_rtl_candidate"}
        or not description
        or not verification_goal
        or not rationale
    ):
        raise RuntimeError("Firecrawl returned an invalid artifact proposal")
    return ArtifactDraft(
        kind=f"firecrawl_{kind}",
        description=f"{description} Verification goal: {verification_goal}",
        candidate_path="demo/fifo/fifo_fixed.sv",
        candidate_label="allowlisted_fixture:fifo_fixed.sv",
        hypothesis_claim=hypothesis.claim,
        notes=(
            f"{rationale} Firecrawl cannot choose or write the RTL path; "
            "JacVerify re-verifies the checked-in reviewed fixture."
        ),
    )


def rank_hypotheses(failure: FailureEvidence) -> list[HypothesisDraft]:
    if llm_mode() == "mock":
        return rank_hypotheses_mock(failure)
    if llm_backend() == "firecrawl":
        return rank_hypotheses_firecrawl(failure)
    raise RuntimeError(
        "Live hypothesis ranking is Jac-native; call "
        "rank_hypotheses_for_run in jacverify/store.jac. This Python adapter "
        "only owns the deterministic mock implementation."
    )


def generate_artifact(
    hypothesis: HypothesisDraft,
    module_name: str,
) -> ArtifactDraft:
    if llm_mode() == "mock":
        return generate_artifact_mock(hypothesis, module_name)
    if llm_backend() == "firecrawl":
        return generate_artifact_firecrawl(hypothesis, module_name)
    raise RuntimeError(
        "Live artifact proposal is Jac-native; call "
        "generate_artifact_for_run in jacverify/store.jac. This Python adapter "
        "only owns the deterministic mock implementation."
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


def make_artifact_draft(
    *,
    kind: str,
    description: str,
    candidate_path: str,
    candidate_label: str,
    hypothesis_claim: str,
    notes: str,
) -> ArtifactDraft:
    """Build the Python DTO after Jac validates the typed LLM response."""
    return ArtifactDraft(
        kind=kind,
        description=description,
        candidate_path=candidate_path,
        candidate_label=candidate_label,
        hypothesis_claim=hypothesis_claim,
        notes=notes,
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
    spec_relpath: str
    test_relpath: str
    accepted_filenames: tuple[str, ...]


@dataclass(frozen=True)
class UploadMatch:
    accepted: bool
    case_id: str
    case_title: str
    message: str
    filename: str
    spec_filename: str = ""
    generated_test_filename: str = "generated_tb_wrap.sv"


CURATED_CASES: tuple[CuratedCase, ...] = tuple(
    CuratedCase(
        case_id=cfg.case_id,
        title=cfg.title,
        description=(
            f"{cfg.description} Hackathon demo uses a reviewed fix fixture "
            "for re-verification."
        ),
        buggy_relpath="demo/fifo/fifo_buggy.sv",
        spec_relpath="demo/fifo/fifo_spec.md",
        test_relpath="demo/fifo/tb_wrap.sv",
        accepted_filenames=("fifo_buggy.sv", "fifo.sv"),
    ),
)


def list_curated_cases() -> list[dict[str, str]]:
    return [
        {
            "case_id": case.case_id,
            "title": case.title,
            "description": case.description,
            "buggy_relpath": case.buggy_relpath,
            "spec_relpath": case.spec_relpath,
            "test_relpath": case.test_relpath,
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


def identify_uploaded_inputs(
    workspace_root: str,
    design_filename: str,
    design_content: str,
    spec_filename: str,
    spec_content: str,
) -> UploadMatch:
    """Validate design/spec inputs and recognize optional curated fixtures."""
    design_basename = _safe_upload_name(design_filename, "design.sv")
    spec_basename = _safe_upload_name(spec_filename, "spec.md")
    if not design_content or not design_content.strip():
        return UploadMatch(
            accepted=False,
            case_id="",
            case_title="",
            message="Upload an RTL design file to continue.",
            filename=design_basename,
            spec_filename=spec_basename,
        )
    if not spec_content or not spec_content.strip():
        return UploadMatch(
            accepted=False,
            case_id="",
            case_title="",
            message="Upload a specification file to continue.",
            filename=design_basename,
            spec_filename=spec_basename,
        )
    try:
        _module_name(design_content, "Uploaded design")
    except ValueError as exc:
        return UploadMatch(
            accepted=False,
            case_id="",
            case_title="",
            message=str(exc),
            filename=design_basename,
            spec_filename=spec_basename,
        )

    design_fp = source_fingerprint(design_content)
    spec_fp = source_fingerprint(spec_content)
    for case in CURATED_CASES:
        root = Path(workspace_root).resolve()
        design_path = root / case.buggy_relpath
        spec_path = root / case.spec_relpath
        if not design_path.is_file() or not spec_path.is_file():
            continue
        if (
            design_fp == source_fingerprint(design_path.read_text(encoding="utf-8"))
            and spec_fp == source_fingerprint(spec_path.read_text(encoding="utf-8"))
        ):
            return UploadMatch(
                accepted=True,
                case_id=case.case_id,
                case_title=case.title,
                message=(
                    f"Ready: `{design_basename}` and `{spec_basename}` match "
                    "the reviewed FIFO fixture. JacVerify will generate the "
                    "prototype wraparound testbench."
                ),
                filename=design_basename,
                spec_filename=spec_basename,
            )

    return UploadMatch(
        accepted=True,
        case_id="uploaded",
        case_title="Spec-driven design verification",
        message=(
            f"Ready: `{design_basename}` will be checked against "
            f"`{spec_basename}` using the prototype generated FIFO testbench."
        ),
        filename=design_basename,
        spec_filename=spec_basename,
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

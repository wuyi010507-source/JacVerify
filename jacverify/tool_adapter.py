"""Deterministic, allow-listed adapter for the JacVerify FIFO demo."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ToolRun:
    stage: str
    status: str
    exit_code: int
    command: list[str]
    duration_ms: int
    stdout: str
    stderr: str
    artifact_paths: list[str]


@dataclass(frozen=True)
class FifoSuiteEvidence:
    lint: ToolRun
    smoke: ToolRun
    failing_regression: ToolRun
    patched_reverify: ToolRun


def _execute(
    *,
    stage: str,
    command: list[str],
    cwd: Path,
    expected_exit_code: int = 0,
    artifact_paths: list[Path] | None = None,
) -> ToolRun:
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ToolRun(
        stage=stage,
        status="passed" if completed.returncode == expected_exit_code else "failed",
        exit_code=completed.returncode,
        command=command,
        duration_ms=duration_ms,
        stdout=completed.stdout,
        stderr=completed.stderr,
        artifact_paths=[str(path) for path in artifact_paths or []],
    )


def _compile_and_run(
    *,
    stage: str,
    rtl: Path,
    testbench: Path,
    output_dir: Path,
    expected_sim_exit_code: int,
) -> ToolRun:
    binary = output_dir / f"{stage}.vvp"
    compile_command = [
        "iverilog",
        "-g2012",
        "-s",
        testbench.stem,
        "-o",
        str(binary),
        str(rtl),
        str(testbench),
    ]
    compile_result = _execute(
        stage=f"{stage}_compile",
        command=compile_command,
        cwd=output_dir,
        artifact_paths=[binary],
    )
    if compile_result.status != "passed":
        return ToolRun(
            stage=stage,
            status="failed",
            exit_code=compile_result.exit_code,
            command=compile_result.command,
            duration_ms=compile_result.duration_ms,
            stdout=compile_result.stdout,
            stderr=compile_result.stderr,
            artifact_paths=compile_result.artifact_paths,
        )

    simulation = _execute(
        stage=stage,
        command=["vvp", str(binary)],
        cwd=output_dir,
        expected_exit_code=expected_sim_exit_code,
        artifact_paths=[binary],
    )
    if expected_sim_exit_code != 0 and simulation.exit_code == expected_sim_exit_code:
        return ToolRun(
            stage=simulation.stage,
            status="failed",
            exit_code=simulation.exit_code,
            command=simulation.command,
            duration_ms=compile_result.duration_ms + simulation.duration_ms,
            stdout=simulation.stdout,
            stderr=simulation.stderr,
            artifact_paths=simulation.artifact_paths,
        )
    return ToolRun(
        stage=simulation.stage,
        status=simulation.status,
        exit_code=simulation.exit_code,
        command=simulation.command,
        duration_ms=compile_result.duration_ms + simulation.duration_ms,
        stdout=simulation.stdout,
        stderr=simulation.stderr,
        artifact_paths=simulation.artifact_paths,
    )


def run_fifo_suite(workspace_root: str, output_dir: str) -> FifoSuiteEvidence:
    root = Path(workspace_root).resolve()
    artifacts = Path(output_dir).resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    fifo_dir = root / "demo" / "fifo"

    buggy_rtl = fifo_dir / "fifo_buggy.sv"
    fixed_rtl = fifo_dir / "fifo_fixed.sv"
    smoke_tb = fifo_dir / "tb_smoke.sv"
    wrap_tb = fifo_dir / "tb_wrap.sv"
    allowlisted_inputs = [buggy_rtl, fixed_rtl, smoke_tb, wrap_tb]
    if not all(path.is_file() and fifo_dir in path.parents for path in allowlisted_inputs):
        raise FileNotFoundError("FIFO demo inputs are missing or outside the allow-listed directory")

    lint = _execute(
        stage="lint",
        command=["iverilog", "-g2012", "-tnull", "-s", "fifo", str(buggy_rtl)],
        cwd=artifacts,
    )
    smoke = _compile_and_run(
        stage="smoke",
        rtl=buggy_rtl,
        testbench=smoke_tb,
        output_dir=artifacts,
        expected_sim_exit_code=0,
    )
    failing_regression = _compile_and_run(
        stage="wrap_regression",
        rtl=buggy_rtl,
        testbench=wrap_tb,
        output_dir=artifacts,
        expected_sim_exit_code=1,
    )
    patched_reverify = _compile_and_run(
        stage="patched_reverify",
        rtl=fixed_rtl,
        testbench=wrap_tb,
        output_dir=artifacts,
        expected_sim_exit_code=0,
    )

    evidence = FifoSuiteEvidence(
        lint=lint,
        smoke=smoke,
        failing_regression=failing_regression,
        patched_reverify=patched_reverify,
    )
    manifest = artifacts / "tool_evidence.json"
    manifest.write_text(json.dumps(asdict(evidence), indent=2), encoding="utf-8")
    return evidence


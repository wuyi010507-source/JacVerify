"""Allow-listed FIFO tool adapter with explicit mock/live modes."""

from __future__ import annotations

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

WRAP_MISMATCH_RE = re.compile(
    r"WRAP_MISMATCH\s+expected=([0-9A-Fa-f]+)\s+observed=([0-9A-Fa-f]+)"
)


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


def _fifo_paths(workspace_root: str) -> dict[str, Path]:
    root = Path(workspace_root).resolve()
    fifo_dir = root / "demo" / "fifo"
    paths = {
        "root": root,
        "fifo_dir": fifo_dir,
        "buggy_rtl": fifo_dir / "fifo_buggy.sv",
        "fixed_rtl": fifo_dir / "fifo_fixed.sv",
        "smoke_tb": fifo_dir / "tb_smoke.sv",
        "wrap_tb": fifo_dir / "tb_wrap.sv",
        "spec_path": fifo_dir / "fifo_spec.md",
    }
    for key in ("buggy_rtl", "fixed_rtl", "smoke_tb", "wrap_tb", "spec_path"):
        path = paths[key]
        if not path.is_file() or fifo_dir not in path.parents:
            raise FileNotFoundError(
                f"FIFO demo input missing or outside allow-list: {path}"
            )
    return paths


def load_spec(workspace_root: str) -> SpecLoadResult:
    paths = _fifo_paths(workspace_root)
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
        raise ValueError("FIFO demo specification must contain exactly five requirements")
    return SpecLoadResult(
        requirement_count=len(requirements),
        spec_path=str(paths["spec_path"]),
        requirements=requirements,
        module_path=str(paths["buggy_rtl"]),
        module_name="fifo",
        mode=tools_mode(),
    )


def parse_failure_evidence(result: ToolResult) -> FailureEvidence | None:
    match = WRAP_MISMATCH_RE.search(result.stdout or "")
    if not match:
        return None
    return FailureEvidence(
        kind="WRAP_MISMATCH",
        expected=match.group(1),
        observed=match.group(2),
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
    return ToolResult(
        tool="iverilog",
        mode="mock",
        status=STATUS_PASSED,
        exit_code=0,
        command=["mock:iverilog", "-g2012", "-tnull", "-s", "fifo", "fifo_buggy.sv"],
        duration_ms=1,
        stdout="mock lint/compile ok\n",
        stderr="",
        artifacts=[],
        diagnostics={"stage": "compile"},
    )


def _mock_smoke() -> ToolResult:
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
        diagnostics={"stage": "smoke", "test": "tb_smoke"},
    )


def _mock_regression(*, reproduce_bug: bool = True) -> ToolResult:
    if reproduce_bug:
        stdout = "WRAP_MISMATCH expected=55 observed=33\n"
        return ToolResult(
            tool="vvp",
            mode="mock",
            status=STATUS_VERIFICATION_FAILED,
            exit_code=1,
            command=["mock:vvp", "wrap_regression.vvp"],
            duration_ms=2,
            stdout=stdout,
            stderr="",
            artifacts=["mock:wrap_regression.vvp"],
            diagnostics={"stage": "wrap_regression", "test": "tb_wrap"},
        )
    return ToolResult(
        tool="vvp",
        mode="mock",
        status=STATUS_BUG_NOT_REPRODUCED,
        exit_code=0,
        command=["mock:vvp", "wrap_regression.vvp"],
        duration_ms=2,
        stdout="WRAP_TEST_PASS\n",
        stderr="",
        artifacts=["mock:wrap_regression.vvp"],
        diagnostics={"stage": "wrap_regression", "test": "tb_wrap"},
    )


def _mock_reverify(*, pass_result: bool = True) -> ToolResult:
    if pass_result:
        return ToolResult(
            tool="vvp",
            mode="mock",
            status=STATUS_PASSED,
            exit_code=0,
            command=["mock:vvp", "patched_reverify.vvp"],
            duration_ms=2,
            stdout="WRAP_TEST_PASS\n",
            stderr="",
            artifacts=["mock:patched_reverify.vvp"],
            diagnostics={
                "stage": "patched_reverify",
                "candidate": "demo/fifo/fifo_fixed.sv",
                "candidate_kind": "reviewed_fixture",
            },
        )
    return ToolResult(
        tool="vvp",
        mode="mock",
        status=STATUS_VERIFICATION_FAILED,
        exit_code=1,
        command=["mock:vvp", "patched_reverify.vvp"],
        duration_ms=2,
        stdout="WRAP_MISMATCH expected=55 observed=33\n",
        stderr="",
        artifacts=["mock:patched_reverify.vvp"],
        diagnostics={
            "stage": "patched_reverify",
            "candidate": "demo/fifo/fifo_fixed.sv",
            "candidate_kind": "reviewed_fixture",
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
    paths = _fifo_paths(workspace_root)
    artifacts = _ensure_output_dir(output_dir)
    result = _execute(
        tool="iverilog",
        command=[
            "iverilog",
            "-g2012",
            "-tnull",
            "-s",
            "fifo",
            str(paths["buggy_rtl"]),
        ],
        cwd=artifacts,
        diagnostics={"stage": "compile"},
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
    if tools_mode() == "mock":
        return _mock_smoke()
    paths = _fifo_paths(workspace_root)
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
    if tools_mode() == "mock":
        force = os.environ.get("JACVERIFY_FORCE_BUG_NOT_REPRODUCED", "")
        return _mock_regression(reproduce_bug=force != "1")
    paths = _fifo_paths(workspace_root)
    artifacts = _ensure_output_dir(output_dir)
    result = _compile_and_simulate(
        stage="wrap_regression",
        rtl=paths["buggy_rtl"],
        testbench=paths["wrap_tb"],
        output_dir=artifacts,
    )
    if result.status == STATUS_TOOL_ERROR and result.diagnostics.get("error"):
        return result
    if "WRAP_MISMATCH" in result.stdout:
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
            diagnostics={**result.diagnostics, "stage": "wrap_regression"},
        )
    if "WRAP_TEST_PASS" in result.stdout or result.exit_code == 0:
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
            diagnostics={**result.diagnostics, "stage": "wrap_regression"},
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
            "stage": "wrap_regression",
            "error": "malformed_output",
        },
    )


def run_reverify(
    workspace_root: str,
    output_dir: str,
    attempt: int = 1,
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
    }
    if result.status == STATUS_PASSED and "WRAP_TEST_PASS" in result.stdout:
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
    if "WRAP_MISMATCH" in result.stdout:
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
    """Deterministic diagnosis aligned with the planted write-pointer wrap bug."""
    expected = failure.expected or "?"
    observed = failure.observed or "?"
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
    return ArtifactDraft(
        kind="reviewed_candidate_fixture",
        description=(
            f"Directed wraparound reverify artifact for module `{module_name}`: "
            "apply pre-reviewed candidate `demo/fifo/fifo_fixed.sv` that restores "
            "write_ptr wrap-to-zero, then rerun tb_wrap."
        ),
        candidate_path="demo/fifo/fifo_fixed.sv",
        candidate_label="reviewed_fixture:fifo_fixed.sv",
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

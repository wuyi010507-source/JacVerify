from dataclasses import dataclass


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
    spec_requirement_count: int
    spec_path: str
    lint: ToolRun
    smoke: ToolRun
    failing_regression: ToolRun
    patched_reverify: ToolRun


def run_fifo_suite(workspace_root: str, output_dir: str) -> FifoSuiteEvidence: ...

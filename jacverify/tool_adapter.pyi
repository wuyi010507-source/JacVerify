from typing import Any

STATUS_PASSED: str
STATUS_VERIFICATION_FAILED: str
STATUS_TOOL_ERROR: str
STATUS_BUG_NOT_REPRODUCED: str
STATUS_NOT_RUN: str


class ToolResult:
    tool: str
    mode: str
    status: str
    exit_code: int | None
    command: list[str]
    duration_ms: int
    stdout: str
    stderr: str
    artifacts: list[str]
    diagnostics: dict[str, Any]


class FailureEvidence:
    kind: str
    expected: str | None
    observed: str | None
    cycle: int | None
    raw_stdout: str
    source_result: ToolResult


class RequirementItem:
    req_id: str
    text: str


class SpecLoadResult:
    requirement_count: int
    spec_path: str
    requirements: list[RequirementItem]
    module_path: str
    module_name: str
    mode: str


class HypothesisDraft:
    rank: int
    claim: str
    confidence: float
    next_action: str


class ArtifactDraft:
    kind: str
    description: str
    candidate_path: str
    candidate_label: str
    hypothesis_claim: str
    notes: str


class FifoSuiteEvidence:
    spec_requirement_count: int
    spec_path: str
    lint: ToolResult
    smoke: ToolResult
    failing_regression: ToolResult
    patched_reverify: ToolResult


ToolRun = ToolResult


def tools_mode() -> str: ...
def llm_mode() -> str: ...
def llm_backend() -> str: ...
def load_spec(workspace_root: str) -> SpecLoadResult: ...
def lint_compile(workspace_root: str, output_dir: str) -> ToolResult: ...
def run_smoke(workspace_root: str, output_dir: str) -> ToolResult: ...
def run_wrap_regression(workspace_root: str, output_dir: str) -> ToolResult: ...
def run_reverify(
    workspace_root: str, output_dir: str, attempt: int = 1
) -> ToolResult: ...
def parse_failure_evidence(result: ToolResult) -> FailureEvidence | None: ...
def parse_failure_from_stored(
    *,
    tool: str,
    mode: str,
    status: str,
    exit_code: int,
    stdout: str,
) -> FailureEvidence | None: ...
def rank_hypotheses(failure: FailureEvidence) -> list[HypothesisDraft]: ...
def generate_artifact(
    hypothesis: HypothesisDraft, module_name: str
) -> ArtifactDraft: ...
def rank_hypotheses_mock(failure: FailureEvidence) -> list[HypothesisDraft]: ...
def rank_hypotheses_firecrawl(
    failure: FailureEvidence,
) -> list[HypothesisDraft]: ...
def generate_artifact_mock(
    hypothesis: HypothesisDraft, module_name: str
) -> ArtifactDraft: ...
def generate_artifact_firecrawl(
    hypothesis: HypothesisDraft, module_name: str
) -> ArtifactDraft: ...
def make_hypothesis_draft(
    rank: int, claim: str, confidence: float, next_action: str
) -> HypothesisDraft: ...
def make_artifact_draft(
    *,
    kind: str,
    description: str,
    candidate_path: str,
    candidate_label: str,
    hypothesis_claim: str,
    notes: str,
) -> ArtifactDraft: ...
def fresh_run_id(prefix: str = "fifo-run") -> str: ...
def run_fifo_suite(workspace_root: str, output_dir: str) -> FifoSuiteEvidence: ...

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


class CoverageResult:
    available: bool
    code_coverage: float
    functional_coverage: float
    source: str


class UploadedInputPaths:
    design_path: str
    spec_path: str
    test_path: str
    design_module: str
    test_module: str


class GeneratedTestbench:
    filename: str
    path: str
    module_name: str
    mode: str
    notes: str


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


class LLMJobStatus:
    job_id: str
    kind: str
    status: str
    attempt: int
    max_attempts: int
    error: str
    generated_testbench: GeneratedTestbench | None
    hypotheses: list[HypothesisDraft]
    artifact: ArtifactDraft | None


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
def testgen_mode() -> str: ...
def load_spec(workspace_root: str) -> SpecLoadResult: ...
def load_uploaded_spec(
    spec_path: str, module_path: str, module_name: str
) -> SpecLoadResult: ...
def lint_compile(
    workspace_root: str,
    output_dir: str,
    design_path: str = "",
    test_path: str = "",
    top_module: str = "",
) -> ToolResult: ...
def run_smoke(workspace_root: str, output_dir: str) -> ToolResult: ...
def run_wrap_regression(workspace_root: str, output_dir: str) -> ToolResult: ...
def run_uploaded_test(
    workspace_root: str,
    output_dir: str,
    design_path: str,
    test_path: str,
) -> ToolResult: ...
def run_reverify(
    workspace_root: str,
    output_dir: str,
    attempt: int = 1,
    test_path: str = "",
    candidate_path: str = "",
) -> ToolResult: ...
def coverage_from_result(result: ToolResult) -> CoverageResult: ...
def materialize_uploaded_inputs(
    workspace_root: str,
    output_dir: str,
    design_filename: str,
    design_content: str,
    spec_filename: str,
    spec_content: str,
) -> UploadedInputPaths: ...
def generate_testbench_for_run(
    workspace_root: str,
    output_dir: str,
    design_path: str,
    spec_path: str,
) -> GeneratedTestbench: ...
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
def start_testbench_generation_job(
    workspace_root: str,
    output_dir: str,
    design_path: str,
    spec_path: str,
) -> str: ...
def start_hypothesis_ranking_job(failure: FailureEvidence) -> str: ...
def start_artifact_generation_job(
    hypothesis: HypothesisDraft, module_name: str
) -> str: ...
def poll_llm_job(job_id: str) -> LLMJobStatus: ...
def discard_llm_job(job_id: str) -> None: ...
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


class UploadMatch:
    accepted: bool
    case_id: str
    case_title: str
    message: str
    filename: str
    spec_filename: str
    generated_test_filename: str


def set_active_case(case_id: str) -> str: ...
def get_active_case_id() -> str: ...
def is_curated_case_id(case_id: str) -> bool: ...
def allowlisted_candidate_path(case_id: str = "") -> str: ...
def read_text_file(path: str) -> str: ...
def render_code_diff(
    before_path: str,
    after_path: str,
    before_label: str = "before",
    after_label: str = "after",
) -> str: ...
def publish_candidate_output(
    workspace_root: str,
    output_dir: str,
    candidate_path: str,
) -> str: ...
def text_file_data_url(path: str) -> str: ...
def identify_uploaded_case(
    workspace_root: str, filename: str, content: str
) -> UploadMatch: ...
def identify_uploaded_inputs(
    workspace_root: str,
    design_filename: str,
    design_content: str,
    spec_filename: str,
    spec_content: str,
) -> UploadMatch: ...
def load_curated_case_upload(
    workspace_root: str, case_id: str = "fifo"
) -> UploadMatch: ...
def list_curated_cases() -> list[dict[str, str]]: ...
def run_fifo_suite(workspace_root: str, output_dir: str) -> FifoSuiteEvidence: ...

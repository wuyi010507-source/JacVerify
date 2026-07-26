"""JacVerify graph model, seven-walker FIFO pipeline, and dashboard endpoints."""

import os;
import from jacverify.tool_adapter {
    ArtifactDraft,
    CoverageResult,
    FailureEvidence,
    HypothesisDraft,
    SpecLoadResult,
    ToolResult,
    UploadMatch,
    UploadedInputPaths,
    coverage_from_result,
    fresh_run_id,
    generate_artifact,
    identify_uploaded_inputs,
    lint_compile,
    llm_backend,
    llm_mode,
    load_spec,
    materialize_uploaded_inputs,
    make_artifact_draft,
    make_hypothesis_draft,
    read_text_file,
    parse_failure_from_stored,
    rank_hypotheses,
    run_reverify,
    run_uploaded_test,
    tools_mode
}
import from jacverify.llm_calls {
    ArtifactProposalOutput,
    FifoFailureContext,
    HypothesisRankingOutput,
    RankedHypothesisOutput,
    propose_fifo_artifact,
    rank_fifo_failure
}

# ---------------------------------------------------------------------------
# Project-level demo graph (preserved for the optional priorities tab)
# ---------------------------------------------------------------------------

node Project {
    has project_id: str,
        name: str,
        milestone: str,
        remaining_budget: float;
}

node ActionCandidate {
    has target: str,
        action: str,
        impact: float,
        severity: float,
        confidence: float,
        urgency: float,
        estimated_cost: float,
        reason: str = "",
        risk: str = "low",
        source_kind: str = "scenario",
        evidence_ids: list[str] = [];
}

edge HasAction: Project --> ActionCandidate {}

# ---------------------------------------------------------------------------
# Core verification evidence graph
# ---------------------------------------------------------------------------

node Requirement {
    has req_id: str,
        text: str,
        run_id: str,
        source_walker: str = "LoadInputsWalker";
}

node Module {
    has module_name: str,
        rtl_path: str,
        run_id: str,
        source_walker: str = "LoadInputsWalker";
}

node Test {
    has test_id: str,
        name: str,
        kind: str,
        run_id: str,
        status: str = "NOT_RUN",
        stdout: str = "",
        coverage_available: bool = False,
        code_coverage: float = 0.0,
        functional_coverage: float = 0.0,
        coverage_source: str = "not_reported",
        source_walker: str = "";
}

node Run {
    has run_id: str,
        title: str,
        current_state: str = "S0_SPEC_INGEST",
        status: str = "running",
        tool_mode: str = "mock",
        llm_mode: str = "mock",
        workspace_root: str = "",
        output_dir: str = "",
        stop_reason: str = "",
        walker_log: list[str] = [],
        requirement_count: int = 0,
        module_name: str = "",
        module_path: str = "",
        compile_status: str = "NOT_RUN",
        compile_stdout: str = "",
        smoke_status: str = "NOT_RUN",
        smoke_stdout: str = "",
        regression_status: str = "NOT_RUN",
        regression_stdout: str = "",
        regression_tool: str = "",
        regression_exit_code: int = -1,
        failure_kind: str = "",
        failure_expected: str = "",
        failure_observed: str = "",
        failure_cycle: str = "",
        top_hypothesis: str = "",
        top_confidence: float = 0.0,
        debug_attempt: int = 0,
        max_debug_attempts: int = 3,
        selected_hypothesis_rank: int = 0,
        needs_user_review: bool = False,
        artifact_description: str = "",
        candidate_label: str = "",
        candidate_path: str = "",
        candidate_applied: bool = False,
        reverify_status: str = "NOT_RUN",
        reverify_stdout: str = "",
        graph_hint: str = "/graph",
        case_id: str = "",
        case_title: str = "",
        uploaded_filename: str = "",
        uploaded_test_filename: str = "",
        input_design_path: str = "",
        input_test_path: str = "",
        testbench_name: str = "",
        reviewed_candidate_available: bool = False,
        coverage_available: bool = False,
        code_coverage: float = 0.0,
        functional_coverage: float = 0.0,
        coverage_source: str = "not_reported";
}

node Failure {
    has kind: str,
        expected: str,
        observed: str,
        raw_stdout: str,
        run_id: str,
        cycle: str = "",
        source_walker: str = "StructureFailureWalker";
}

node Hypothesis {
    has rank: int,
        claim: str,
        confidence: float,
        next_action: str,
        run_id: str,
        status: str = "pending",
        attempt_number: int = 0,
        rejection_reason: str = "",
        source_walker: str = "RankHypothesesWalker";
}

node Artifact {
    has kind: str,
        description: str,
        candidate_path: str,
        candidate_label: str,
        run_id: str,
        attempt_number: int = 0,
        status: str = "generated",
        reverify_status: str = "NOT_RUN",
        source_walker: str = "GenerateArtifactWalker";
}

edge Verifies: Requirement --> Test {}
edge Targets: Test --> Module {}
edge Executes: Run --> Test {}
edge FailedWith: Run --> Failure {}
edge Motivates: Failure --> Hypothesis {}
edge Produces: Hypothesis --> Artifact {}
edge ReverifiedBy: Artifact --> Run {}
edge OwnsModule: Run --> Module {}
edge OwnsRequirement: Run --> Requirement {}

node TransitionRecord {
    has sequence: int,
        from_state: str,
        to_state: str,
        event: str,
        summary: str,
        evidence_kind: str,
        evidence_ids: list[str],
        walker_name: str = "";
}

edge HasTransition: Run --> TransitionRecord {}

# Legacy job node retained for existing StateExecutor unit tests.
node VerificationJob {
    has job_id: str,
        title: str,
        current_state: str = "S0_SPEC_INGEST",
        status: str = "running";
}

edge HasJobTransition: VerificationJob --> TransitionRecord {}

# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------

obj PriorityRecommendation {
    has rank: int,
        target: str,
        action: str,
        reason: str,
        expected_impact: float,
        estimated_cost: float,
        risk: str,
        confidence: float,
        score: float,
        source_kind: str,
        evidence_ids: list[str];
}

obj PlannedTransition {
    has to_state: str,
        event: str,
        summary: str,
        evidence_kind: str,
        evidence_ids: list[str];
}

obj TransitionView {
    has sequence: int,
        from_state: str,
        to_state: str,
        event: str,
        summary: str,
        evidence_kind: str,
        evidence_ids: list[str],
        walker_name: str = "";
}

obj DashboardData {
    has project_name: str,
        milestone: str,
        remaining_budget: float,
        failure_events: int,
        root_cause_clusters: int,
        coverage_percent: float,
        recommendations: list[PriorityRecommendation],
        data_note: str;
}

obj DemoRunResult {
    has job_id: str,
        current_state: str,
        status: str,
        transitions: list[TransitionView],
        tool_evidence_available: bool,
        requirement_count: int,
        toolchain: str,
        regression_output: str,
        reverify_output: str,
        artifact_manifest: str,
        tool_mode: str = "mock",
        llm_mode: str = "mock",
        walker_log: list[str] = [],
        compile_status: str = "NOT_RUN",
        smoke_status: str = "NOT_RUN",
        regression_status: str = "NOT_RUN",
        reverify_status: str = "NOT_RUN",
        failure_kind: str = "",
        failure_expected: str = "",
        failure_observed: str = "",
        failure_cycle: str = "",
        top_hypothesis: str = "",
        top_confidence: float = 0.0,
        debug_attempt: int = 0,
        max_debug_attempts: int = 3,
        selected_hypothesis_rank: int = 0,
        needs_user_review: bool = False,
        artifact_description: str = "",
        candidate_label: str = "",
        candidate_applied: bool = False,
        stop_reason: str = "",
        graph_hint: str = "/graph",
        case_id: str = "",
        case_title: str = "",
        uploaded_filename: str = "",
        uploaded_test_filename: str = "",
        coverage_available: bool = False,
        code_coverage: float = 0.0,
        functional_coverage: float = 0.0,
        coverage_source: str = "not_reported",
        upload_accepted: bool = False;
}

obj UploadPreview {
    has accepted: bool,
        case_id: str,
        case_title: str,
        message: str,
        filename: str,
        test_filename: str,
        curated_hint: str;
}

# ---------------------------------------------------------------------------
# Project scoring (preserved)
# ---------------------------------------------------------------------------

def score_action(candidate: ActionCandidate) -> float {
    if candidate.estimated_cost <= 0.0 {
        return 0.0;
    }
    return (
        candidate.impact
        * candidate.severity
        * candidate.confidence
        * candidate.urgency
        / candidate.estimated_cost
    );
}

def rank_action_names(candidates: list[ActionCandidate]) -> list[str] {
    ranked = sorted(
        candidates,
        key=lambda (candidate: ActionCandidate) {
            -score_action(candidate);
        }
    );
    return [
        f"{candidate.target}: {candidate.action}"
        for candidate in ranked
    ];
}

def build_recommendations(
    candidates: list[ActionCandidate]
) -> list[PriorityRecommendation] {
    ranked = sorted(
        candidates,
        key=lambda (candidate: ActionCandidate) {
            -score_action(candidate);
        }
    );
    recommendations: list[PriorityRecommendation] = [];
    rank: int = 1;
    for candidate in ranked {
        recommendations.append(
            PriorityRecommendation(
                rank=rank,
                target=candidate.target,
                action=candidate.action,
                reason=candidate.reason,
                expected_impact=candidate.impact,
                estimated_cost=candidate.estimated_cost,
                risk=candidate.risk,
                confidence=candidate.confidence,
                score=score_action(candidate),
                source_kind=candidate.source_kind,
                evidence_ids=candidate.evidence_ids
            )
        );
        rank += 1;
    }
    return recommendations;
}

def seed_demo_project(target_project_id: str) -> Project {
    existing: list[Project] = [root -->[?:Project]];
    for project in existing {
        if project.project_id == target_project_id {
            return project;
        }
    }

    project = root ++> Project(
        project_id=target_project_id,
        name="Atlas SoC",
        milestone="Tape-out readiness · T-9 days",
        remaining_budget=8.0
    );

    project +>:HasAction:+> ActionCandidate(
        target="Module A · FIFO",
        action="Run a directed wraparound reverify",
        reason=(
            "A high-confidence root-cause cluster explains 12 severe failures, "
            "and the directed run has low compute cost."
        ),
        impact=9.0,
        severity=5.0,
        confidence=0.9,
        urgency=1.0,
        estimated_cost=2.0,
        risk="low",
        source_kind="mixed",
        evidence_ids=[
            "tool:run-104",
            "tool:scoreboard-mismatch-cycle-37",
            "scenario:milestone-t-minus-9"
        ]
    );
    project +>:HasAction:+> ActionCandidate(
        target="Module B · Coverage",
        action="Pause broad random regression",
        reason=(
            "The last five runs added only 0.3% coverage while consuming most "
            "of the remaining run budget."
        ),
        impact=7.0,
        severity=3.0,
        confidence=0.6,
        urgency=0.8,
        estimated_cost=5.0,
        risk="medium",
        source_kind="scenario",
        evidence_ids=[
            "scenario:coverage-snapshot-07",
            "scenario:compute-budget"
        ]
    );
    project +>:HasAction:+> ActionCandidate(
        target="Module C · Environment",
        action="Repair test configuration before touching RTL",
        reason=(
            "Four failures share an environment signature, so an RTL patch "
            "would be unsupported by the available evidence."
        ),
        impact=5.0,
        severity=4.0,
        confidence=0.8,
        urgency=0.9,
        estimated_cost=1.5,
        risk="low",
        source_kind="scenario",
        evidence_ids=[
            "scenario:failure-cluster-03",
            "scenario:adapter-config-diff"
        ]
    );
    return project;
}

# ---------------------------------------------------------------------------
# Legacy FSM helpers (validation / unit tests only — not the demo story)
# ---------------------------------------------------------------------------

def create_fifo_job(target_job_id: str) -> VerificationJob {
    existing: list[VerificationJob] = [root -->[?:VerificationJob]];
    for job in existing {
        if job.job_id == target_job_id {
            return job;
        }
    }
    return root ++> VerificationJob(
        job_id=target_job_id,
        title="FIFO wraparound verification"
    );
}

def plan_transition(current_state: str) -> PlannedTransition {
    if current_state == "S0_SPEC_INGEST" {
        return PlannedTransition(
            to_state="S3_STATIC_CHECK",
            event="spec_and_design_loaded",
            summary="Five FIFO requirements mapped to the RTL module.",
            evidence_kind="tool_fact",
            evidence_ids=["tool:spec-parser", "tool:design-index"]
        );
    }
    if current_state == "S3_STATIC_CHECK" {
        return PlannedTransition(
            to_state="S4_COMPILE_ELAB",
            event="lint_pass",
            summary="Static checks completed with no blocking diagnostics.",
            evidence_kind="tool_fact",
            evidence_ids=["tool:lint-result-001"]
        );
    }
    if current_state == "S4_COMPILE_ELAB" {
        return PlannedTransition(
            to_state="S6_REGRESSION",
            event="compile_and_smoke_pass",
            summary="Compile and smoke tests passed; fixed-seed regression started.",
            evidence_kind="tool_fact",
            evidence_ids=["tool:compile-result-002", "tool:smoke-run-003"]
        );
    }
    if current_state == "S6_REGRESSION" {
        return PlannedTransition(
            to_state="D0_FAILURE_NORMALIZE",
            event="scoreboard_mismatch",
            summary="Icarus Verilog observed a deterministic mismatch after pointer wrap.",
            evidence_kind="tool_fact",
            evidence_ids=["tool:wrap_regression.vvp", "tool:WRAP_MISMATCH"]
        );
    }
    if current_state == "D0_FAILURE_NORMALIZE" {
        return PlannedTransition(
            to_state="D1_HYPOTHESIS_RANK",
            event="failure_normalized",
            summary="Likely missing wrap bit in the write pointer; confidence 0.91.",
            evidence_kind="model_inference",
            evidence_ids=["tool:run-104", "graph:requirement-fifo-order"]
        );
    }
    if current_state == "D1_HYPOTHESIS_RANK" {
        return PlannedTransition(
            to_state="D2_SELECT_REMEDIATION",
            event="hypothesis_ranked",
            summary="Prefer a DEPTH+2 directed test before proposing an RTL change.",
            evidence_kind="action_recommendation",
            evidence_ids=["graph:hypothesis-wrap-bit", "policy:low-risk-first"]
        );
    }
    if current_state == "D2_SELECT_REMEDIATION" {
        return PlannedTransition(
            to_state="D3_GENERATE_ARTIFACT",
            event="action_allowed",
            summary="Generated a bounded wraparound test under the action whitelist.",
            evidence_kind="action_recommendation",
            evidence_ids=["policy:generate-test", "artifact:test-fifo-wrap"]
        );
    }
    if current_state == "D3_GENERATE_ARTIFACT" {
        return PlannedTransition(
            to_state="D5_TARGETED_REVERIFY",
            event="artifact_validated",
            summary="Directed test passed static safety checks and entered reverify.",
            evidence_kind="tool_fact",
            evidence_ids=["tool:test-syntax-check", "artifact:test-fifo-wrap"]
        );
    }
    if current_state == "D5_TARGETED_REVERIFY" {
        return PlannedTransition(
            to_state="S9_SIGNOFF_GATE",
            event="targeted_reverify_pass",
            summary="The same directed test passed against the pre-approved patch fixture.",
            evidence_kind="tool_fact",
            evidence_ids=["tool:patched_reverify.vvp", "tool:WRAP_TEST_PASS"]
        );
    }
    if current_state == "S9_SIGNOFF_GATE" {
        return PlannedTransition(
            to_state="DONE",
            event="demo_gate_met",
            summary="Requirement-to-evidence trace is complete for the demo scope.",
            evidence_kind="tool_fact",
            evidence_ids=["graph:requirement-trace", "policy:demo-signoff"]
        );
    }
    return PlannedTransition(
        to_state="BLOCKED",
        event="unknown_state",
        summary="The state requires human review.",
        evidence_kind="action_recommendation",
        evidence_ids=["policy:human-gate"]
    );
}

# ---------------------------------------------------------------------------
# Run helpers
# ---------------------------------------------------------------------------

def new_run_id() -> str {
    return fresh_run_id("fifo-run");
}

def append_transition(
    run: Run,
    from_state: str,
    to_state: str,
    event: str,
    summary: str,
    evidence_kind: str,
    evidence_ids: list[str],
    walker_name: str
) -> TransitionView {
    sequence = len([run ->:HasTransition:->]) + 1;
    run +>:HasTransition:+> TransitionRecord(
        sequence=sequence,
        from_state=from_state,
        to_state=to_state,
        event=event,
        summary=summary,
        evidence_kind=evidence_kind,
        evidence_ids=evidence_ids,
        walker_name=walker_name
    );
    run.current_state = to_state;
    if not run.walker_log or run.walker_log[-1] != walker_name {
        run.walker_log = run.walker_log + [walker_name];
    }
    return TransitionView(
        sequence=sequence,
        from_state=from_state,
        to_state=to_state,
        event=event,
        summary=summary,
        evidence_kind=evidence_kind,
        evidence_ids=evidence_ids,
        walker_name=walker_name
    );
}

def block_run(run: Run, reason: str, walker_name: str) -> None {
    run.status = "blocked";
    run.stop_reason = reason;
    run.current_state = "BLOCKED";
    if walker_name not in run.walker_log {
        run.walker_log = run.walker_log + [walker_name];
    }
}

def request_user_review(
    run: Run,
    reason: str,
    event: str,
    evidence_kind: str,
    evidence_ids: list[str],
    walker_name: str
) -> None {
    from_state = run.current_state;
    append_transition(
        run,
        from_state,
        "NEEDS_USER_REVIEW",
        event,
        reason,
        evidence_kind,
        evidence_ids,
        walker_name
    );
    run.status = "blocked";
    run.stop_reason = reason;
    run.needs_user_review = True;
    run.current_state = "NEEDS_USER_REVIEW";
}

def list_run_transitions(run: Run) -> list[TransitionView] {
    records = sorted(
        [run ->:HasTransition:->],
        key=lambda (record: TransitionRecord) {
            record.sequence;
        }
    );
    return [
        TransitionView(
            sequence=record.sequence,
            from_state=record.from_state,
            to_state=record.to_state,
            event=record.event,
            summary=record.summary,
            evidence_kind=record.evidence_kind,
            evidence_ids=record.evidence_ids,
            walker_name=record.walker_name
        )
        for record in records
    ];
}

def build_demo_result(run: Run) -> DemoRunResult {
    toolchain = (
        "Icarus Verilog · mock adapters"
        if run.tool_mode == "mock"
        else "Icarus Verilog · live iverilog/vvp"
    );
    tool_ok = (
        run.status == "complete"
        and run.compile_status == "PASSED"
        and (
            run.regression_status == "PASSED"
            or (
                run.regression_status == "VERIFICATION_FAILED"
                and run.reverify_status == "PASSED"
                and run.candidate_applied
            )
        )
    );
    return DemoRunResult(
        job_id=run.run_id,
        current_state=run.current_state,
        status=run.status,
        transitions=list_run_transitions(run),
        tool_evidence_available=tool_ok,
        requirement_count=run.requirement_count,
        toolchain=toolchain,
        regression_output=run.regression_stdout.strip(),
        reverify_output=run.reverify_stdout.strip(),
        artifact_manifest=os.path.join(run.output_dir, "tool_evidence.json"),
        tool_mode=run.tool_mode,
        llm_mode=run.llm_mode,
        walker_log=run.walker_log,
        compile_status=run.compile_status,
        smoke_status=run.smoke_status,
        regression_status=run.regression_status,
        reverify_status=run.reverify_status,
        failure_kind=run.failure_kind,
        failure_expected=run.failure_expected,
        failure_observed=run.failure_observed,
        failure_cycle=run.failure_cycle,
        top_hypothesis=run.top_hypothesis,
        top_confidence=run.top_confidence,
        debug_attempt=run.debug_attempt,
        max_debug_attempts=run.max_debug_attempts,
        selected_hypothesis_rank=run.selected_hypothesis_rank,
        needs_user_review=run.needs_user_review,
        artifact_description=run.artifact_description,
        candidate_label=run.candidate_label,
        candidate_applied=run.candidate_applied,
        stop_reason=run.stop_reason,
        graph_hint=run.graph_hint,
        case_id=run.case_id,
        case_title=run.case_title,
        uploaded_filename=run.uploaded_filename,
        uploaded_test_filename=run.uploaded_test_filename,
        coverage_available=run.coverage_available,
        code_coverage=run.code_coverage,
        functional_coverage=run.functional_coverage,
        coverage_source=run.coverage_source,
        upload_accepted=run.case_id != ""
    );
}

def rejected_upload_result(upload_match: UploadMatch) -> DemoRunResult {
    return DemoRunResult(
        job_id="upload-rejected",
        current_state="BLOCKED",
        status="blocked",
        transitions=[],
        tool_evidence_available=False,
        requirement_count=0,
        toolchain="upload gate · curated cases only",
        regression_output="",
        reverify_output="",
        artifact_manifest="",
        tool_mode=tools_mode(),
        llm_mode=llm_mode(),
        walker_log=[],
        stop_reason=upload_match.message,
        case_id="",
        case_title="",
        uploaded_filename=upload_match.filename,
        uploaded_test_filename=upload_match.test_filename,
        upload_accepted=False
    );
}

def run_case_pipeline(
    case_id: str,
    case_title: str,
    design_filename: str,
    design_content: str,
    test_filename: str,
    test_content: str
) -> DemoRunResult {
    workspace_root = os.getcwd();
    run_id = new_run_id();
    output_dir = os.path.join(workspace_root, "runs", run_id);
    inputs: UploadedInputPaths = materialize_uploaded_inputs(
        output_dir,
        design_filename,
        design_content,
        test_filename,
        test_content
    );
    run = root ++> Run(
        run_id=run_id,
        title=case_title + " verification",
        current_state="S0_SPEC_INGEST",
        status="running",
        tool_mode=tools_mode(),
        llm_mode=llm_mode(),
        workspace_root=workspace_root,
        output_dir=output_dir,
        graph_hint="/graph",
        case_id=case_id,
        case_title=case_title,
        uploaded_filename=design_filename,
        uploaded_test_filename=test_filename,
        input_design_path=inputs.design_path,
        input_test_path=inputs.test_path,
        module_name=inputs.design_module,
        module_path=inputs.design_path,
        testbench_name=inputs.test_module,
        reviewed_candidate_available=case_id == "fifo"
    );

    root spawn LoadInputsWalker(run_id=run_id);
    if run.status == "running" {
        root spawn CompileWalker(run_id=run_id);
    }
    if run.status == "running" {
        root spawn SimulateWalker(run_id=run_id);
    }
    if run.status == "running" {
        root spawn StructureFailureWalker(run_id=run_id);
    }
    if run.status == "running" {
        root spawn RankHypothesesWalker(run_id=run_id);
    }
    while (
        run.status == "running"
        and run.current_state == "D3_GENERATE_ARTIFACT"
    ) {
        root spawn GenerateArtifactWalker(run_id=run_id);
        if run.status == "running" {
            root spawn ReverifyAndRenderWalker(run_id=run_id);
        }
    }
    return build_demo_result(run);
}

# ---------------------------------------------------------------------------
# Constrained LLM wrappers (typed interface; mock by default)
# ---------------------------------------------------------------------------

# Keep the first live prompt small and tied to the checked-in FIFO requirements.
def fifo_failure_context(
    module_name: str,
    failure_kind: str,
    expected: str,
    observed: str,
    cycle: str,
    tool_output: str
) -> FifoFailureContext {
    return FifoFailureContext(
        module_name=module_name,
        requirements=[
            "Reset leaves the FIFO empty and ready to accept a write.",
            "Values are read in the same order in which they were accepted.",
            "The FIFO accepts exactly DEPTH entries before asserting full.",
            "A read while empty does not advance the read pointer.",
            "A simultaneous accepted read and write preserves occupancy."
        ],
        failure_kind=failure_kind,
        expected=expected,
        observed=observed,
        cycle=cycle,
        tool_output=tool_output
    );
}

# Rank diagnostic hypotheses only. Never declares design PASS/FAIL.
def rank_hypotheses_for_run(failure: FailureEvidence) -> list[HypothesisDraft] {
    if llm_mode() == "mock" or llm_backend() == "firecrawl" {
        return rank_hypotheses(failure);
    }
    context = fifo_failure_context(
        "fifo",
        failure.kind,
        failure.expected if failure.expected is not None else "",
        failure.observed if failure.observed is not None else "",
        str(failure.cycle) if failure.cycle is not None else "",
        failure.raw_stdout
    );
    ranking: HypothesisRankingOutput = rank_fifo_failure(context);
    drafts: list[HypothesisDraft] = [];
    for item in ranking.hypotheses {
        if item.rank < 1 or item.confidence < 0.0 or item.confidence > 1.0 {
            continue;
        }
        drafts.append(
            make_hypothesis_draft(
                item.rank,
                item.claim,
                item.confidence,
                item.next_action
            )
        );
    }
    return sorted(
        drafts,
        key=lambda (item: HypothesisDraft) {
            item.rank;
        }
    );
}

# Draft a reviewed candidate description. The LLM never controls the path.
def generate_artifact_for_run(
    hypothesis: HypothesisDraft,
    module_name: str,
    failure_kind: str,
    expected: str,
    observed: str,
    cycle: str,
    tool_output: str
) -> ArtifactDraft {
    if llm_mode() == "mock" or llm_backend() == "firecrawl" {
        return generate_artifact(hypothesis, module_name);
    }
    context = fifo_failure_context(
        module_name,
        failure_kind,
        expected,
        observed,
        cycle,
        tool_output
    );
    top = RankedHypothesisOutput(
        rank=hypothesis.rank,
        claim=hypothesis.claim,
        confidence=hypothesis.confidence,
        next_action=hypothesis.next_action
    );
    proposal: ArtifactProposalOutput = propose_fifo_artifact(context, top);
    return make_artifact_draft(
        kind="llm_reviewed_candidate_proposal",
        description=(
            f"{proposal.description} Verification goal: "
            f"{proposal.verification_goal}"
        ),
        candidate_path="demo/fifo/fifo_fixed.sv",
        candidate_label="allowlisted_fixture:fifo_fixed.sv",
        hypothesis_claim=hypothesis.claim,
        notes=(
            f"{proposal.rationale} The model cannot choose or write the RTL "
            "path; JacVerify re-verifies the checked-in reviewed fixture."
        )
    );
}

# ---------------------------------------------------------------------------
# Seven walkers
# ---------------------------------------------------------------------------

walker LoadInputsWalker {
    has run_id: str;

    can find_run with Root entry {
        visit [here -->[?:Run, run_id == self.run_id]];
    }

    can load_inputs with Run entry {
        if here.status != "running" {
            skip;
        }
        if here.current_state != "S0_SPEC_INGEST" {
            block_run(here, "LoadInputsWalker expected S0_SPEC_INGEST", "LoadInputsWalker");
            skip;
        }
        try {
            if not here.input_design_path or not here.input_test_path {
                raise ValueError("Uploaded design/test paths are missing");
            }
            module_node = here +>:OwnsModule:+> Module(
                module_name=here.module_name,
                rtl_path=here.input_design_path,
                run_id=here.run_id,
                source_walker="LoadInputsWalker"
            );
            evidence_ids = [here.input_design_path, here.input_test_path];
            if here.case_id == "fifo" {
                spec: SpecLoadResult = load_spec(here.workspace_root);
                here.requirement_count = spec.requirement_count;
                for req in spec.requirements {
                    here +>:OwnsRequirement:+> Requirement(
                        req_id=req.req_id,
                        text=req.text,
                        run_id=here.run_id,
                        source_walker="LoadInputsWalker"
                    );
                }
                evidence_ids.append(spec.spec_path);
            } else {
                here.requirement_count = 1;
                here +>:OwnsRequirement:+> Requirement(
                    req_id="REQ-UPLOADED-TEST",
                    text=(
                        "The uploaded testbench defines the executable "
                        "pass/fail contract for this run."
                    ),
                    run_id=here.run_id,
                    source_walker="LoadInputsWalker"
                );
            }
            append_transition(
                here,
                "S0_SPEC_INGEST",
                "S3_STATIC_CHECK",
                "design_and_test_loaded",
                (
                    f"Loaded design module {here.module_name} and uploaded "
                    f"testbench {here.testbench_name}."
                ),
                "tool_fact",
                evidence_ids,
                "LoadInputsWalker"
            );
        } except Exception as exc {
            block_run(here, "LoadInputsWalker failed: " + str(exc), "LoadInputsWalker");
            append_transition(
                here,
                "S0_SPEC_INGEST",
                "BLOCKED",
                "load_inputs_failed",
                str(exc),
                "tool_fact",
                ["error:load_inputs"],
                "LoadInputsWalker"
            );
        }
    }
}

walker CompileWalker {
    has run_id: str;

    can find_run with Root entry {
        visit [here -->[?:Run, run_id == self.run_id]];
    }

    can compile with Run entry {
        if here.status != "running" {
            skip;
        }
        if here.current_state != "S3_STATIC_CHECK" {
            block_run(here, "CompileWalker missing loaded inputs", "CompileWalker");
            skip;
        }
        if here.requirement_count <= 0 or not here.module_path {
            block_run(here, "CompileWalker refused: inputs missing", "CompileWalker");
            skip;
        }
        result: ToolResult = lint_compile(
            here.workspace_root,
            here.output_dir,
            here.input_design_path,
            here.input_test_path,
            here.testbench_name
        );
        here.compile_status = result.status;
        here.compile_stdout = result.stdout;
        if result.status == "PASSED" {
            append_transition(
                here,
                "S3_STATIC_CHECK",
                "S4_COMPILE_ELAB",
                "lint_compile_passed",
                f"Compile/lint {result.status} via {result.tool} ({result.mode}).",
                "tool_fact",
                [f"tool:{result.tool}", f"status:{result.status}"],
                "CompileWalker"
            );
        } else {
            block_run(
                here,
                f"TOOL_ERROR during compile: {result.stderr or result.stdout}",
                "CompileWalker"
            );
            append_transition(
                here,
                "S3_STATIC_CHECK",
                "BLOCKED",
                "lint_compile_tool_error",
                f"Compile stopped with {result.status}.",
                "tool_fact",
                [f"status:{result.status}"],
                "CompileWalker"
            );
        }
    }
}

walker SimulateWalker {
    has run_id: str;

    can find_run with Root entry {
        visit [here -->[?:Run, run_id == self.run_id]];
    }

    can simulate with Run entry {
        if here.status != "running" {
            skip;
        }
        if here.current_state != "S4_COMPILE_ELAB" {
            block_run(here, "SimulateWalker refused: compile stage incomplete", "SimulateWalker");
            skip;
        }
        if here.compile_status != "PASSED" {
            block_run(here, "SimulateWalker refused: compile not PASSED", "SimulateWalker");
            skip;
        }

        modules: list[Module] = [here ->:OwnsModule:->];
        if not modules {
            block_run(here, "SimulateWalker refused: Module node missing", "SimulateWalker");
            skip;
        }
        module_node = modules[0];

        regression: ToolResult = run_uploaded_test(
            here.workspace_root,
            here.output_dir,
            here.input_design_path,
            here.input_test_path
        );
        here.regression_status = regression.status;
        here.regression_stdout = regression.stdout;
        here.regression_tool = regression.tool;
        coverage: CoverageResult = coverage_from_result(regression);
        here.coverage_available = coverage.available;
        here.code_coverage = coverage.code_coverage;
        here.functional_coverage = coverage.functional_coverage;
        here.coverage_source = coverage.source;
        if regression.exit_code is not None {
            here.regression_exit_code = regression.exit_code;
        } else {
            here.regression_exit_code = -1;
        }
        uploaded_test = here +>:Executes:+> Test(
            test_id=here.run_id + ":uploaded-test",
            name=here.testbench_name,
            kind="uploaded",
            status=regression.status,
            stdout=regression.stdout,
            coverage_available=coverage.available,
            code_coverage=coverage.code_coverage,
            functional_coverage=coverage.functional_coverage,
            coverage_source=coverage.source,
            run_id=here.run_id,
            source_walker="SimulateWalker"
        );
        uploaded_test +>:Targets:+> module_node;
        for req in [here ->:OwnsRequirement:->] {
            req +>:Verifies:+> uploaded_test;
        }

        if regression.status == "VERIFICATION_FAILED" {
            append_transition(
                here,
                "S4_COMPILE_ELAB",
                "S6_REGRESSION",
                "uploaded_test_failed",
                (
                    f"Uploaded testbench {here.testbench_name} reported "
                    "VERIFICATION_FAILED."
                ),
                "tool_fact",
                [
                    f"status:{regression.status}",
                    f"test:{here.uploaded_test_filename}"
                ],
                "SimulateWalker"
            );
            append_transition(
                here,
                "S6_REGRESSION",
                "D0_FAILURE_NORMALIZE",
                "ready_to_structure_failure",
                "Defect evidence available for structuring.",
                "tool_fact",
                [f"test:{here.uploaded_test_filename}"],
                "SimulateWalker"
            );
        } elif regression.status == "PASSED" {
            append_transition(
                here,
                "S4_COMPILE_ELAB",
                "S9_SIGNOFF_GATE",
                "uploaded_test_passed",
                f"Uploaded testbench {here.testbench_name} passed.",
                "tool_fact",
                [f"status:{regression.status}"],
                "SimulateWalker"
            );
            append_transition(
                here,
                "S9_SIGNOFF_GATE",
                "DONE",
                "evidence_trace_complete",
                "Uploaded design/test evidence is ready for inspection.",
                "tool_fact",
                ["graph:/graph", f"run:{here.run_id}"],
                "SimulateWalker"
            );
            here.status = "complete";
            here.current_state = "DONE";
        } else {
            block_run(
                here,
                f"TOOL_ERROR during regression: {regression.stderr or regression.stdout}",
                "SimulateWalker"
            );
            append_transition(
                here,
                "S4_COMPILE_ELAB",
                "BLOCKED",
                "regression_tool_error",
                f"Regression stopped with {regression.status}.",
                "tool_fact",
                [f"status:{regression.status}"],
                "SimulateWalker"
            );
        }
    }
}

walker StructureFailureWalker {
    has run_id: str;

    can find_run with Root entry {
        visit [here -->[?:Run, run_id == self.run_id]];
    }

    can structure_failure with Run entry {
        if here.status != "running" {
            skip;
        }
        if here.current_state != "D0_FAILURE_NORMALIZE" {
            block_run(here, "StructureFailureWalker refused: wrong state", "StructureFailureWalker");
            skip;
        }
        if here.regression_status != "VERIFICATION_FAILED" {
            block_run(
                here,
                "StructureFailureWalker refused: regression was not VERIFICATION_FAILED",
                "StructureFailureWalker"
            );
            skip;
        }
        failure: FailureEvidence | None = parse_failure_from_stored(
            tool=here.regression_tool if here.regression_tool else "vvp",
            mode=here.tool_mode,
            status=here.regression_status,
            exit_code=here.regression_exit_code,
            stdout=here.regression_stdout
        );
        if failure is None {
            block_run(
                here,
                "TOOL_ERROR: WRAP_MISMATCH could not be parsed from regression stdout",
                "StructureFailureWalker"
            );
            append_transition(
                here,
                "D0_FAILURE_NORMALIZE",
                "BLOCKED",
                "failure_parse_error",
                "Parser could not extract expected/observed from regression output.",
                "tool_fact",
                ["error:parse_failure"],
                "StructureFailureWalker"
            );
            skip;
        }
        here.failure_kind = failure.kind;
        if failure.expected is not None {
            here.failure_expected = failure.expected;
        } else {
            here.failure_expected = "";
        }
        if failure.observed is not None {
            here.failure_observed = failure.observed;
        } else {
            here.failure_observed = "";
        }
        if failure.cycle is not None {
            here.failure_cycle = str(failure.cycle);
        } else {
            here.failure_cycle = "";
        }
        here +>:FailedWith:+> Failure(
            kind=failure.kind,
            expected=here.failure_expected,
            observed=here.failure_observed,
            cycle=here.failure_cycle,
            raw_stdout=failure.raw_stdout,
            run_id=here.run_id,
            source_walker="StructureFailureWalker"
        );
        append_transition(
            here,
            "D0_FAILURE_NORMALIZE",
            "D1_HYPOTHESIS_RANK",
            "failure_structured",
            f"{failure.kind} expected={here.failure_expected} observed={here.failure_observed}",
            "tool_fact",
            [f"failure:{failure.kind}", f"expected:{here.failure_expected}", f"observed:{here.failure_observed}"],
            "StructureFailureWalker"
        );
    }
}

walker RankHypothesesWalker {
    has run_id: str;

    can find_run with Root entry {
        visit [here -->[?:Run, run_id == self.run_id]];
    }

    can rank with Run entry {
        if here.status != "running" {
            skip;
        }
        if here.current_state != "D1_HYPOTHESIS_RANK" {
            request_user_review(
                here,
                "RankHypothesesWalker refused: wrong state",
                "debug_state_requires_review",
                "graph_invariant",
                ["error:wrong_state"],
                "RankHypothesesWalker"
            );
            skip;
        }
        if not here.reviewed_candidate_available {
            request_user_review(
                here,
                (
                    "The uploaded test failed and its evidence was captured. "
                    "Automatic remediation is disabled because this design has "
                    "no reviewed candidate fixture."
                ),
                "uploaded_test_failure_requires_review",
                "policy_decision",
                [
                    f"design:{here.uploaded_filename}",
                    f"test:{here.uploaded_test_filename}"
                ],
                "RankHypothesesWalker"
            );
            skip;
        }
        failures: list[Failure] = [here ->:FailedWith:->];
        if not failures {
            request_user_review(
                here,
                "RankHypothesesWalker refused: Failure node missing",
                "failure_evidence_requires_review",
                "graph_invariant",
                ["error:failure_missing"],
                "RankHypothesesWalker"
            );
            skip;
        }
        failure_node = failures[0];
        evidence: FailureEvidence | None = parse_failure_from_stored(
            tool=here.regression_tool if here.regression_tool else "vvp",
            mode=here.tool_mode,
            status=here.regression_status,
            exit_code=here.regression_exit_code,
            stdout=here.regression_stdout
        );
        if evidence is None {
            request_user_review(
                here,
                "RankHypothesesWalker refused: missing structured evidence",
                "failure_evidence_requires_review",
                "tool_fact",
                ["error:structured_evidence_missing"],
                "RankHypothesesWalker"
            );
            skip;
        }
        try {
            drafts: list[HypothesisDraft] = rank_hypotheses_for_run(evidence);
            if not drafts {
                request_user_review(
                    here,
                    "RankHypothesesWalker produced no hypotheses",
                    "hypothesis_ranking_requires_review",
                    "model_inference",
                    ["error:no_hypotheses"],
                    "RankHypothesesWalker"
                );
                skip;
            }
            top = drafts[0];
            here.top_hypothesis = top.claim;
            here.top_confidence = top.confidence;
            here.selected_hypothesis_rank = top.rank;
            for draft in drafts {
                failure_node +>:Motivates:+> Hypothesis(
                    rank=draft.rank,
                    claim=draft.claim,
                    confidence=draft.confidence,
                    next_action=draft.next_action,
                    run_id=here.run_id,
                    status="selected" if draft.rank == top.rank else "pending",
                    source_walker="RankHypothesesWalker"
                );
            }
            append_transition(
                here,
                "D1_HYPOTHESIS_RANK",
                "D2_SELECT_REMEDIATION",
                "hypotheses_ranked",
                f"Top hypothesis confidence={top.confidence}: {top.claim}",
                "model_inference",
                [f"hypothesis:rank-1", f"llm_mode:{here.llm_mode}"],
                "RankHypothesesWalker"
            );
            append_transition(
                here,
                "D2_SELECT_REMEDIATION",
                "D3_GENERATE_ARTIFACT",
                "remediation_selected",
                top.next_action,
                "action_recommendation",
                ["policy:reviewed-candidate-first"],
                "RankHypothesesWalker"
            );
        } except Exception as exc {
            request_user_review(
                here,
                "RankHypothesesWalker failed: " + str(exc),
                "hypothesis_ranking_requires_review",
                "model_inference",
                ["error:llm"],
                "RankHypothesesWalker"
            );
        }
    }
}

walker GenerateArtifactWalker {
    has run_id: str;

    can find_run with Root entry {
        visit [here -->[?:Run, run_id == self.run_id]];
    }

    can generate with Run entry {
        if here.status != "running" {
            skip;
        }
        if here.current_state != "D3_GENERATE_ARTIFACT" {
            request_user_review(
                here,
                "GenerateArtifactWalker refused: wrong state",
                "debug_state_requires_review",
                "graph_invariant",
                ["error:wrong_state"],
                "GenerateArtifactWalker"
            );
            skip;
        }
        failures: list[Failure] = [here ->:FailedWith:->];
        if not failures {
            request_user_review(
                here,
                "GenerateArtifactWalker refused: Failure missing",
                "failure_evidence_requires_review",
                "graph_invariant",
                ["error:failure_missing"],
                "GenerateArtifactWalker"
            );
            skip;
        }
        hyps: list[Hypothesis] = [failures[0] ->:Motivates:->];
        if not hyps {
            request_user_review(
                here,
                "GenerateArtifactWalker refused: Hypothesis missing",
                "hypothesis_ranking_requires_review",
                "graph_invariant",
                ["error:hypothesis_missing"],
                "GenerateArtifactWalker"
            );
            skip;
        }
        ranked: list[Hypothesis] = sorted(
            hyps,
            key=lambda (item: Hypothesis) {
                item.rank;
            }
        );
        selected = [
            item for item in ranked
            if item.rank == here.selected_hypothesis_rank
            and item.status == "selected"
        ];
        if not selected {
            request_user_review(
                here,
                "No selected hypothesis is available for the next debug attempt.",
                "selected_hypothesis_missing",
                "action_recommendation",
                [f"selected_rank:{here.selected_hypothesis_rank}"],
                "GenerateArtifactWalker"
            );
            skip;
        }
        if here.debug_attempt >= here.max_debug_attempts {
            request_user_review(
                here,
                f"Debug attempt limit {here.max_debug_attempts} reached before artifact generation.",
                "debug_attempt_limit_reached",
                "policy_decision",
                [f"attempts:{here.debug_attempt}"],
                "GenerateArtifactWalker"
            );
            skip;
        }
        top = selected[0];
        here.debug_attempt += 1;
        top.attempt_number = here.debug_attempt;
        draft_in = make_hypothesis_draft(
            top.rank,
            top.claim,
            top.confidence,
            top.next_action
        );
        module_name = "fifo";
        if here.module_name {
            module_name = here.module_name;
        }
        try {
            artifact_draft: ArtifactDraft = generate_artifact_for_run(
                draft_in,
                module_name,
                failures[0].kind,
                failures[0].expected,
                failures[0].observed,
                failures[0].cycle,
                failures[0].raw_stdout
            );
            here.artifact_description = artifact_draft.description;
            here.candidate_label = artifact_draft.candidate_label;
            here.candidate_path = artifact_draft.candidate_path;
            top +>:Produces:+> Artifact(
                kind=artifact_draft.kind,
                description=artifact_draft.description,
                candidate_path=artifact_draft.candidate_path,
                candidate_label=artifact_draft.candidate_label,
                run_id=here.run_id,
                attempt_number=here.debug_attempt,
                status="generated",
                source_walker="GenerateArtifactWalker"
            );
            append_transition(
                here,
                "D3_GENERATE_ARTIFACT",
                "D4_APPLY_CANDIDATE",
                "artifact_generated",
                artifact_draft.description,
                "action_recommendation",
                [
                    artifact_draft.candidate_label,
                    f"llm_mode:{here.llm_mode}",
                    f"attempt:{here.debug_attempt}",
                    f"hypothesis:rank-{top.rank}"
                ],
                "GenerateArtifactWalker"
            );
        } except Exception as exc {
            request_user_review(
                here,
                "GenerateArtifactWalker failed: " + str(exc),
                "artifact_generation_requires_review",
                "action_recommendation",
                ["error:llm", f"attempt:{here.debug_attempt}"],
                "GenerateArtifactWalker"
            );
        }
    }
}

walker ReverifyAndRenderWalker {
    has run_id: str;

    can find_run with Root entry {
        visit [here -->[?:Run, run_id == self.run_id]];
    }

    can reverify_and_render with Run entry {
        if here.status != "running" {
            skip;
        }
        if here.current_state != "D4_APPLY_CANDIDATE" {
            request_user_review(
                here,
                "ReverifyAndRenderWalker refused: wrong state",
                "debug_state_requires_review",
                "graph_invariant",
                ["error:wrong_state"],
                "ReverifyAndRenderWalker"
            );
            skip;
        }
        if not here.candidate_path {
            request_user_review(
                here,
                "ReverifyAndRenderWalker refused: candidate missing",
                "artifact_missing",
                "graph_invariant",
                ["error:candidate_missing"],
                "ReverifyAndRenderWalker"
            );
            skip;
        }
        failures: list[Failure] = [here ->:FailedWith:->];
        hypotheses: list[Hypothesis] = [];
        if failures {
            hypotheses = [
                hyp for hyp in [failures[0] ->:Motivates:->]
                if hyp.rank == here.selected_hypothesis_rank
                and hyp.status == "selected"
            ];
        }
        if not hypotheses {
            request_user_review(
                here,
                "ReverifyAndRenderWalker could not resolve the selected hypothesis.",
                "selected_hypothesis_missing",
                "graph_invariant",
                [f"selected_rank:{here.selected_hypothesis_rank}"],
                "ReverifyAndRenderWalker"
            );
            skip;
        }
        selected_hypothesis = hypotheses[0];
        artifacts: list[Artifact] = [
            art for art in [selected_hypothesis ->:Produces:->]
            if art.attempt_number == here.debug_attempt
        ];
        if not artifacts {
            request_user_review(
                here,
                "ReverifyAndRenderWalker could not resolve the current Artifact.",
                "artifact_missing",
                "graph_invariant",
                [f"attempt:{here.debug_attempt}"],
                "ReverifyAndRenderWalker"
            );
            skip;
        }
        artifact_node = artifacts[0];

        # Explicit reviewed-candidate application event (fixture, not auto RTL rewrite).
        here.candidate_applied = True;
        append_transition(
            here,
            "D4_APPLY_CANDIDATE",
            "D5_TARGETED_REVERIFY",
            "reviewed_candidate_applied",
            f"Applied reviewed candidate fixture {here.candidate_label}.",
            "action_recommendation",
            [here.candidate_label, here.candidate_path],
            "ReverifyAndRenderWalker"
        );

        result: ToolResult = run_reverify(
            here.workspace_root,
            here.output_dir,
            here.debug_attempt,
            here.input_test_path,
            here.candidate_path
        );
        here.reverify_status = result.status;
        here.reverify_stdout = result.stdout;
        coverage: CoverageResult = coverage_from_result(result);
        if coverage.available {
            here.coverage_available = True;
            here.code_coverage = coverage.code_coverage;
            here.functional_coverage = coverage.functional_coverage;
            here.coverage_source = coverage.source;
        }
        artifact_node.reverify_status = result.status;
        reverify_run_id = here.run_id + f":reverify:{here.debug_attempt}";
        reverify_state = result.status;
        reverify_status = "failed";
        if result.status == "PASSED" {
            reverify_state = "DONE";
            reverify_status = "complete";
        }
        reverify_run = root ++> Run(
            run_id=reverify_run_id,
            title="FIFO wraparound re-verification",
            current_state=reverify_state,
            status=reverify_status,
            tool_mode=here.tool_mode,
            llm_mode=here.llm_mode,
            workspace_root=here.workspace_root,
            output_dir=here.output_dir,
            reverify_status=result.status,
            reverify_stdout=result.stdout,
            candidate_applied=True,
            candidate_label=here.candidate_label,
            candidate_path=here.candidate_path,
            coverage_available=coverage.available,
            code_coverage=coverage.code_coverage,
            functional_coverage=coverage.functional_coverage,
            coverage_source=coverage.source
        );
        artifact_node +>:ReverifiedBy:+> reverify_run;

        if result.status == "PASSED" {
            selected_hypothesis.status = "supported";
            artifact_node.status = "reverify_passed";
            append_transition(
                here,
                "D5_TARGETED_REVERIFY",
                "S9_SIGNOFF_GATE",
                "reverification_passed",
                "Re-verification PASSED against reviewed candidate fixture.",
                "tool_fact",
                [
                    f"status:{result.status}",
                    f"reverify_run:{reverify_run_id}",
                    f"attempt:{here.debug_attempt}",
                    f"hypothesis:rank-{selected_hypothesis.rank}"
                ],
                "ReverifyAndRenderWalker"
            );
            append_transition(
                here,
                "S9_SIGNOFF_GATE",
                "DONE",
                "evidence_trace_complete",
                "Requirement-to-evidence graph ready for inspection at /graph.",
                "tool_fact",
                ["graph:/graph", f"run:{here.run_id}"],
                "ReverifyAndRenderWalker"
            );
            here.status = "complete";
            here.current_state = "DONE";
        } elif result.status == "VERIFICATION_FAILED" {
            selected_hypothesis.status = "rejected";
            selected_hypothesis.rejection_reason = (
                f"Targeted re-verification still failed on attempt {here.debug_attempt}."
            );
            artifact_node.status = "reverify_failed";
            pending: list[Hypothesis] = sorted(
                [
                    hyp for hyp in [failures[0] ->:Motivates:->]
                    if hyp.status == "pending"
                ],
                key=lambda (item: Hypothesis) {
                    item.rank;
                }
            );
            if here.debug_attempt < here.max_debug_attempts and pending {
                next_hypothesis = pending[0];
                next_hypothesis.status = "selected";
                here.selected_hypothesis_rank = next_hypothesis.rank;
                here.top_hypothesis = next_hypothesis.claim;
                here.top_confidence = next_hypothesis.confidence;
                append_transition(
                    here,
                    "D5_TARGETED_REVERIFY",
                    "D2_SELECT_REMEDIATION",
                    "hypothesis_rejected",
                    (
                        f"Attempt {here.debug_attempt} did not resolve the failure; "
                        f"rejecting rank {selected_hypothesis.rank}."
                    ),
                    "tool_fact",
                    [
                        f"status:{result.status}",
                        f"attempt:{here.debug_attempt}",
                        f"hypothesis:rank-{selected_hypothesis.rank}"
                    ],
                    "ReverifyAndRenderWalker"
                );
                append_transition(
                    here,
                    "D2_SELECT_REMEDIATION",
                    "D3_GENERATE_ARTIFACT",
                    "next_hypothesis_selected",
                    (
                        f"Selected rank {next_hypothesis.rank} for debug attempt "
                        f"{here.debug_attempt + 1}: {next_hypothesis.claim}"
                    ),
                    "policy_decision",
                    [
                        f"next_attempt:{here.debug_attempt + 1}",
                        f"hypothesis:rank-{next_hypothesis.rank}"
                    ],
                    "ReverifyAndRenderWalker"
                );
            } else {
                request_user_review(
                    here,
                    (
                        f"Re-verification failed after {here.debug_attempt} attempts; "
                        "automatic debug stopped for user intervention."
                    ),
                    "debug_attempt_limit_reached",
                    "policy_decision",
                    [
                        f"status:{result.status}",
                        f"attempts:{here.debug_attempt}",
                        f"max_attempts:{here.max_debug_attempts}"
                    ],
                    "ReverifyAndRenderWalker"
                );
            }
        } else {
            artifact_node.status = "reverify_unknown";
            request_user_review(
                here,
                (
                    f"Re-verification returned {result.status}; this case is not "
                    "safe to auto-retry and requires user intervention."
                ),
                "unexpected_reverify_requires_review",
                "tool_fact",
                [
                    f"status:{result.status}",
                    f"attempt:{here.debug_attempt}"
                ],
                "ReverifyAndRenderWalker"
            );
        }
    }
}

# ---------------------------------------------------------------------------
# Legacy walkers preserved for unit tests
# ---------------------------------------------------------------------------

walker ProjectPlanner {
    has project_id: str,
        candidates: list[ActionCandidate] = [],
        reports: list[list[PriorityRecommendation]] = [];

    can find_project with Root entry {
        visit [here -->[?:Project, project_id == self.project_id]];
    }

    can visit_candidates with Project entry {
        visit [here ->:HasAction:->];
    }

    can collect_candidate with ActionCandidate entry {
        self.candidates.append(here);
    }

    can finish with Root exit {
        report build_recommendations(self.candidates);
    }
}

walker StateExecutor {
    has job_id: str,
        transitions: list[TransitionView] = [],
        reports: list[list[TransitionView]] = [];

    can find_job with Root entry {
        visit [here -->[?:VerificationJob, job_id == self.job_id]];
    }

    can execute_state with VerificationJob entry {
        if here.current_state == "DONE" or here.current_state == "BLOCKED" {
            skip;
        }
        plan = plan_transition(here.current_state);
        sequence = len(self.transitions) + 1;
        view = TransitionView(
            sequence=sequence,
            from_state=here.current_state,
            to_state=plan.to_state,
            event=plan.event,
            summary=plan.summary,
            evidence_kind=plan.evidence_kind,
            evidence_ids=plan.evidence_ids,
            walker_name="StateExecutor"
        );
        here +>:HasJobTransition:+> TransitionRecord(
            sequence=view.sequence,
            from_state=view.from_state,
            to_state=view.to_state,
            event=view.event,
            summary=view.summary,
            evidence_kind=view.evidence_kind,
            evidence_ids=view.evidence_ids,
            walker_name="StateExecutor"
        );
        here.current_state = plan.to_state;
        if plan.to_state == "DONE" {
            here.status = "complete";
        } elif plan.to_state == "BLOCKED" {
            here.status = "blocked";
        }
        self.transitions.append(view);
        visit here;
    }

    can finish with Root exit {
        report self.transitions;
    }
}

# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------

def:pub get_dashboard -> DashboardData {
    project = seed_demo_project("jacverify-demo");
    planner = root spawn ProjectPlanner(project_id=project.project_id);
    recommendations = (
        planner.reports[0]
        if planner.reports
        else []
    );
    return DashboardData(
        project_name=project.name,
        milestone=project.milestone,
        remaining_budget=project.remaining_budget,
        failure_events=18,
        root_cause_clusters=3,
        coverage_percent=86.4,
        recommendations=recommendations,
        data_note=(
            "Failure details for Module A come from the executable FIFO demo; "
            "Modules B/C and project constraints are labeled scenario data."
        )
    );
}

def:pub preview_uploaded_inputs(
    design_filename: str,
    design_content: str,
    test_filename: str,
    test_content: str
) -> UploadPreview {
    workspace_root = os.getcwd();
    upload_match: UploadMatch = identify_uploaded_inputs(
        workspace_root,
        design_filename,
        design_content,
        test_filename,
        test_content
    );
    return UploadPreview(
        accepted=upload_match.accepted,
        case_id=upload_match.case_id,
        case_title=upload_match.case_title,
        message=upload_match.message,
        filename=upload_match.filename,
        test_filename=upload_match.test_filename,
        curated_hint=(
            "Any SystemVerilog design/test pair can run. Automatic repair "
            "remains limited to reviewed fixtures."
        )
    );
}

def:pub preview_curated_inputs -> UploadPreview {
    workspace_root = os.getcwd();
    design_path = os.path.join(workspace_root, "demo", "fifo", "fifo_buggy.sv");
    test_path = os.path.join(workspace_root, "demo", "fifo", "tb_wrap.sv");
    return preview_uploaded_inputs(
        "fifo_buggy.sv",
        read_text_file(design_path),
        "tb_wrap.sv",
        read_text_file(test_path)
    );
}

# Upload-driven entry: the simulator receives exactly these two file contents.
def:pub run_uploaded_inputs(
    design_filename: str,
    design_content: str,
    test_filename: str,
    test_content: str
) -> DemoRunResult {
    workspace_root = os.getcwd();
    upload_match: UploadMatch = identify_uploaded_inputs(
        workspace_root,
        design_filename,
        design_content,
        test_filename,
        test_content
    );
    if not upload_match.accepted {
        return rejected_upload_result(upload_match);
    }
    return run_case_pipeline(
        upload_match.case_id,
        upload_match.case_title,
        upload_match.filename,
        design_content,
        upload_match.test_filename,
        test_content
    );
}

# Convenience path: loads both curated files through the same generic pair API.
def:pub run_fifo_demo -> DemoRunResult {
    workspace_root = os.getcwd();
    design_path = os.path.join(workspace_root, "demo", "fifo", "fifo_buggy.sv");
    test_path = os.path.join(workspace_root, "demo", "fifo", "tb_wrap.sv");
    return run_uploaded_inputs(
        "fifo_buggy.sv",
        read_text_file(design_path),
        "tb_wrap.sv",
        read_text_file(test_path)
    );
}

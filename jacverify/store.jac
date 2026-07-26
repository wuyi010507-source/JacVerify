"""JacVerify graph model and deterministic decision policy."""

import os;
import from jacverify.tool_adapter { FifoSuiteEvidence, run_fifo_suite }

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

node VerificationJob {
    has job_id: str,
        title: str,
        current_state: str = "S0_SPEC_INGEST",
        status: str = "running";
}

node TransitionRecord {
    has sequence: int,
        from_state: str,
        to_state: str,
        event: str,
        summary: str,
        evidence_kind: str,
        evidence_ids: list[str];
}

edge HasTransition: VerificationJob --> TransitionRecord {}

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
        evidence_ids: list[str];
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
        artifact_manifest: str;
}

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

def list_job_transitions(job: VerificationJob) -> list[TransitionView] {
    records = sorted(
        [job ->:HasTransition:->],
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
            evidence_ids=record.evidence_ids
        )
        for record in records
    ];
}

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
            evidence_ids=plan.evidence_ids
        );
        here +>:HasTransition:+> TransitionRecord(
            sequence=view.sequence,
            from_state=view.from_state,
            to_state=view.to_state,
            event=view.event,
            summary=view.summary,
            evidence_kind=view.evidence_kind,
            evidence_ids=view.evidence_ids
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

def:pub run_fifo_demo -> DemoRunResult {
    workspace_root = os.getcwd();
    output_dir = os.path.join(workspace_root, "runs", "fifo-demo");
    evidence: FifoSuiteEvidence = run_fifo_suite(
        workspace_root,
        output_dir
    );
    tool_evidence_available = (
        evidence.spec_requirement_count == 5
        and evidence.lint.status == "passed"
        and evidence.smoke.status == "passed"
        and evidence.failing_regression.status == "failed"
        and evidence.patched_reverify.status == "passed"
    );
    job = create_fifo_job("fifo-wrap-demo");
    runner = root spawn StateExecutor(job_id=job.job_id);
    transitions = (
        runner.reports[0]
        if runner.reports and runner.reports[0]
        else list_job_transitions(job)
    );
    return DemoRunResult(
        job_id=job.job_id,
        current_state=job.current_state,
        status=job.status,
        transitions=transitions,
        tool_evidence_available=tool_evidence_available,
        requirement_count=evidence.spec_requirement_count,
        toolchain="Icarus Verilog · allow-listed adapter",
        regression_output=evidence.failing_regression.stdout.strip(),
        reverify_output=evidence.patched_reverify.stdout.strip(),
        artifact_manifest=os.path.join(output_dir, "tool_evidence.json")
    );
}

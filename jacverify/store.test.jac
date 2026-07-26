test "ranks the highest evidence-adjusted value first" {
    candidates = [
        ActionCandidate(
            target="FIFO",
            action="Run directed reverify",
            impact=9.0,
            severity=5.0,
            confidence=0.9,
            urgency=1.0,
            estimated_cost=2.0
        ),
        ActionCandidate(
            target="Coverage",
            action="Continue random regression",
            impact=7.0,
            severity=3.0,
            confidence=0.6,
            urgency=0.8,
            estimated_cost=5.0
        ),
        ActionCandidate(
            target="Environment",
            action="Repair test configuration",
            impact=5.0,
            severity=4.0,
            confidence=0.8,
            urgency=0.9,
            estimated_cost=1.5
        )
    ];

    ranked = rank_action_names(candidates);

    assert ranked == [
        "FIFO: Run directed reverify",
        "Environment: Repair test configuration",
        "Coverage: Continue random regression"
    ];
}

test "project planner walks the graph and reports ranked recommendations" {
    project = root ++> Project(
        project_id="demo-project",
        name="Atlas SoC",
        milestone="Tape-out readiness",
        remaining_budget=8.0
    );
    project +>:HasAction:+> ActionCandidate(
        target="Module A · FIFO",
        action="Run a directed wraparound reverify",
        reason="One root-cause cluster explains the most severe failures.",
        impact=9.0,
        severity=5.0,
        confidence=0.9,
        urgency=1.0,
        estimated_cost=2.0,
        risk="low",
        source_kind="mixed",
        evidence_ids=["run-104", "failure-cluster-01"]
    );
    project +>:HasAction:+> ActionCandidate(
        target="Module B · Coverage",
        action="Pause broad random regression",
        reason="Recent runs produced little new coverage.",
        impact=7.0,
        severity=3.0,
        confidence=0.6,
        urgency=0.8,
        estimated_cost=5.0,
        risk="medium",
        source_kind="scenario",
        evidence_ids=["coverage-snapshot-07"]
    );

    result = root spawn ProjectPlanner(project_id="demo-project");
    recommendations = result.reports[0];

    assert len(recommendations) == 2;
    assert recommendations[0].rank == 1;
    assert recommendations[0].target == "Module A · FIFO";
    assert recommendations[0].score > recommendations[1].score;
    assert recommendations[0].source_kind == "mixed";
}

test "demo project seeding is idempotent and produces three choices" {
    first = seed_demo_project("seeded-demo");
    second = seed_demo_project("seeded-demo");
    all_projects: list[Project] = [root -->[?:Project]];
    matches = [
        project for project in all_projects
        if project.project_id == "seeded-demo"
    ];

    assert jid(first) == jid(second);
    assert len(matches) == 1;

    result = root spawn ProjectPlanner(project_id="seeded-demo");
    recommendations = result.reports[0];

    assert len(recommendations) == 3;
    assert recommendations[0].target == "Module A · FIFO";
    assert recommendations[2].target == "Module B · Coverage";
}

test "state executor completes an evidence-labelled FIFO debug loop" {
    job = create_fifo_job("fsm-demo");
    result = root spawn StateExecutor(job_id="fsm-demo");
    transitions = result.reports[0];

    assert job.current_state == "DONE";
    assert len(transitions) == 10;
    assert transitions[3].to_state == "D0_FAILURE_NORMALIZE";
    assert transitions[3].evidence_kind == "tool_fact";
    assert transitions[4].to_state == "D1_HYPOTHESIS_RANK";
    assert transitions[4].evidence_kind == "model_inference";
    assert transitions[5].to_state == "D2_SELECT_REMEDIATION";
    assert transitions[5].evidence_kind == "action_recommendation";
    assert transitions[8].to_state == "S9_SIGNOFF_GATE";
    assert transitions[9].to_state == "DONE";
}

test "seven walkers mock pipeline reaches DONE with structured evidence" {
    first_run = run_fifo_demo();
    second_run = run_fifo_demo();

    assert first_run.job_id != second_run.job_id;
    assert first_run.current_state == "DONE";
    assert first_run.status == "complete";
    assert first_run.tool_mode == "mock";
    assert first_run.llm_mode == "mock";
    assert first_run.requirement_count == 5;
    assert first_run.compile_status == "PASSED";
    assert first_run.smoke_status == "PASSED";
    assert first_run.regression_status == "VERIFICATION_FAILED";
    assert first_run.reverify_status == "PASSED";
    assert first_run.failure_kind == "WRAP_MISMATCH";
    assert first_run.failure_expected == "55";
    assert first_run.failure_observed == "33";
    assert "Write pointer wraps to 1" in first_run.top_hypothesis;
    assert first_run.debug_attempt == 1;
    assert first_run.max_debug_attempts == 3;
    assert first_run.selected_hypothesis_rank == 1;
    assert not first_run.needs_user_review;
    assert first_run.candidate_applied;
    assert first_run.tool_evidence_available;
    assert "WRAP_MISMATCH" in first_run.regression_output;
    assert "WRAP_TEST_PASS" in first_run.reverify_output;

    expected_walkers = [
        "LoadInputsWalker",
        "CompileWalker",
        "SimulateWalker",
        "StructureFailureWalker",
        "RankHypothesesWalker",
        "GenerateArtifactWalker",
        "ReverifyAndRenderWalker"
    ];
    assert first_run.walker_log == expected_walkers;

    walker_names = [
        transition.walker_name
        for transition in first_run.transitions
    ];
    for name in expected_walkers {
        assert name in walker_names;
    }

    runs: list[Run] = [root -->[?:Run, run_id == first_run.job_id]];
    assert len(runs) == 1;
    run = runs[0];
    assert len([run ->:OwnsRequirement:->]) == 5;
    assert len([run ->:OwnsModule:->]) == 1;
    assert len([run ->:Executes:->]) == 2;
    assert len([run ->:FailedWith:->]) == 1;
    failure = [run ->:FailedWith:->][0];
    hyps = [failure ->:Motivates:->];
    assert len(hyps) >= 1;
    arts = [hyps[0] ->:Produces:->];
    assert len(arts) == 1;
    assert len([arts[0] ->:ReverifiedBy:->]) == 1;
}

test "debug loop rejects two hypotheses then succeeds on attempt three" {
    os.environ["JACVERIFY_REVERIFY_SEQUENCE"] = (
        "VERIFICATION_FAILED,VERIFICATION_FAILED,PASSED"
    );
    result = run_fifo_demo();
    os.environ.pop("JACVERIFY_REVERIFY_SEQUENCE", None);

    assert result.status == "complete";
    assert result.current_state == "DONE";
    assert result.debug_attempt == 3;
    assert result.selected_hypothesis_rank == 3;
    assert not result.needs_user_review;
    assert result.reverify_status == "PASSED";

    runs: list[Run] = [root -->[?:Run, run_id == result.job_id]];
    assert len(runs) == 1;
    failure = [runs[0] ->:FailedWith:->][0];
    hypotheses: list[Hypothesis] = sorted(
        [failure ->:Motivates:->],
        key=lambda (item: Hypothesis) {
            item.rank;
        }
    );
    assert len(hypotheses) == 3;
    assert hypotheses[0].status == "rejected";
    assert hypotheses[0].attempt_number == 1;
    assert hypotheses[1].status == "rejected";
    assert hypotheses[1].attempt_number == 2;
    assert hypotheses[2].status == "supported";
    assert hypotheses[2].attempt_number == 3;

    artifacts: list[Artifact] = [];
    for hypothesis in hypotheses {
        for artifact in [hypothesis ->:Produces:->] {
            artifacts.append(artifact);
        }
    }
    assert len(artifacts) == 3;
    assert len([artifacts[0] ->:ReverifiedBy:->]) == 1;
    assert len([artifacts[1] ->:ReverifiedBy:->]) == 1;
    assert len([artifacts[2] ->:ReverifiedBy:->]) == 1;

    events = [transition.event for transition in result.transitions];
    assert events.count("hypothesis_rejected") == 2;
    assert events.count("next_hypothesis_selected") == 2;
    assert "reverification_passed" in events;
}

test "debug loop stops for user review after three failed attempts" {
    os.environ["JACVERIFY_REVERIFY_SEQUENCE"] = (
        "VERIFICATION_FAILED,VERIFICATION_FAILED,VERIFICATION_FAILED"
    );
    result = run_fifo_demo();
    os.environ.pop("JACVERIFY_REVERIFY_SEQUENCE", None);

    assert result.status == "blocked";
    assert result.current_state == "NEEDS_USER_REVIEW";
    assert result.debug_attempt == 3;
    assert result.max_debug_attempts == 3;
    assert result.needs_user_review;
    assert result.reverify_status == "VERIFICATION_FAILED";
    assert "user intervention" in result.stop_reason;
    events = [transition.event for transition in result.transitions];
    assert events.count("hypothesis_rejected") == 2;
    assert events[-1] == "debug_attempt_limit_reached";
}

test "unexpected reverify tool error stops without automatic retry" {
    os.environ["JACVERIFY_REVERIFY_SEQUENCE"] = "TOOL_ERROR";
    result = run_fifo_demo();
    os.environ.pop("JACVERIFY_REVERIFY_SEQUENCE", None);

    assert result.status == "blocked";
    assert result.current_state == "NEEDS_USER_REVIEW";
    assert result.debug_attempt == 1;
    assert result.needs_user_review;
    assert result.reverify_status == "TOOL_ERROR";
    events = [transition.event for transition in result.transitions];
    assert events[-1] == "unexpected_reverify_requires_review";
    assert "hypothesis_rejected" not in events;
}

test "dashboard endpoint still returns project recommendations" {
    dashboard = get_dashboard();
    assert dashboard.failure_events == 18;
    assert dashboard.root_cause_clusters == 3;
    assert len(dashboard.recommendations) == 3;
}

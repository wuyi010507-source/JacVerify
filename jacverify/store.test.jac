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
    matches = [
        root -->[?:Project, project_id == "seeded-demo"]
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

test "public demo data stays complete across repeated reads" {
    dashboard = get_dashboard();
    first_run = run_fifo_demo();
    second_run = run_fifo_demo();

    assert dashboard.failure_events == 18;
    assert dashboard.root_cause_clusters == 3;
    assert len(dashboard.recommendations) == 3;
    assert len(first_run.transitions) == 10;
    assert len(second_run.transitions) == 10;
    assert second_run.current_state == "DONE";
}

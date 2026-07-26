"""Dump one mock seven-walker demo run for verification."""

import from jacverify.store { run_fifo_demo }

with entry {
    result = run_fifo_demo();
    print("RUN", result.job_id);
    print("STATE", result.current_state, result.status);
    print("MODES", result.tool_mode, result.llm_mode);
    print("WALKERS", result.walker_log);
    print("FAIL", result.failure_kind, result.failure_expected, result.failure_observed);
    print("HYP", result.top_hypothesis);
    print(
        "DEBUG",
        f"attempt={result.debug_attempt}/{result.max_debug_attempts}",
        f"selected_rank={result.selected_hypothesis_rank}"
    );
    print("CAND", result.candidate_applied, result.candidate_label);
    print("REVERIFY", result.reverify_status);
    print("USER_REVIEW", result.needs_user_review, result.stop_reason);
    for t in result.transitions {
        print(
            str(t.sequence)
            + ". ["
            + t.walker_name
            + "] "
            + t.from_state
            + " -> "
            + t.to_state
            + " :: "
            + t.event
        );
    }
}

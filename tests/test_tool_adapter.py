from pathlib import Path

from jacverify.tool_adapter import run_fifo_suite


def test_fifo_suite_produces_real_fail_then_pass_evidence(tmp_path: Path) -> None:
    workspace_root = Path(__file__).resolve().parents[1]

    evidence = run_fifo_suite(
        workspace_root=str(workspace_root),
        output_dir=str(tmp_path),
    )

    assert evidence.lint.status == "passed"
    assert evidence.spec_requirement_count == 5
    assert evidence.smoke.status == "passed"
    assert evidence.failing_regression.status == "failed"
    assert "WRAP_MISMATCH" in evidence.failing_regression.stdout
    assert evidence.patched_reverify.status == "passed"
    assert "WRAP_TEST_PASS" in evidence.patched_reverify.stdout

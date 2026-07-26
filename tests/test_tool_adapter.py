import os
from pathlib import Path

import pytest

from jacverify.tool_adapter import (
    STATUS_BUG_NOT_REPRODUCED,
    STATUS_PASSED,
    STATUS_TOOL_ERROR,
    STATUS_VERIFICATION_FAILED,
    generate_artifact,
    identify_uploaded_case,
    lint_compile,
    load_curated_case_upload,
    load_spec,
    parse_failure_evidence,
    rank_hypotheses,
    run_fifo_suite,
    run_reverify,
    run_smoke,
    run_wrap_regression,
    set_active_case,
)


@pytest.fixture(autouse=True)
def _mock_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JACVERIFY_MOCK_TOOLS", "1")
    monkeypatch.setenv("JACVERIFY_MOCK_LLM", "1")
    monkeypatch.delenv("JACVERIFY_FORCE_BUG_NOT_REPRODUCED", raising=False)
    monkeypatch.delenv("JACVERIFY_FORCE_REVERIFY_FAIL", raising=False)
    set_active_case("fifo")


def test_parse_wrap_mismatch_into_failure_evidence() -> None:
    regression = run_wrap_regression(".", "/tmp/jacverify-parse")
    evidence = parse_failure_evidence(regression)
    assert evidence is not None
    assert evidence.kind == "WRAP_MISMATCH"
    assert evidence.expected == "55"
    assert evidence.observed == "33"
    assert evidence.cycle is None


def test_mock_stage_statuses_and_llm_wrappers(tmp_path: Path) -> None:
    workspace = Path(__file__).resolve().parents[1]
    spec = load_spec(str(workspace))
    assert spec.requirement_count == 5

    compile_result = lint_compile(str(workspace), str(tmp_path))
    smoke = run_smoke(str(workspace), str(tmp_path))
    regression = run_wrap_regression(str(workspace), str(tmp_path))
    failure = parse_failure_evidence(regression)
    assert failure is not None
    hypotheses = rank_hypotheses(failure)
    artifact = generate_artifact(hypotheses[0], "fifo")
    reverify = run_reverify(str(workspace), str(tmp_path))

    assert compile_result.status == STATUS_PASSED
    assert smoke.status == STATUS_PASSED
    assert regression.status == STATUS_VERIFICATION_FAILED
    assert hypotheses[0].confidence == 0.91
    assert "write pointer" in hypotheses[0].claim.lower() or "Write pointer" in hypotheses[0].claim
    assert "fifo_fixed.sv" in artifact.candidate_path
    assert reverify.status == STATUS_PASSED


def test_bug_not_reproduced_does_not_invent_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JACVERIFY_FORCE_BUG_NOT_REPRODUCED", "1")
    workspace = Path(__file__).resolve().parents[1]
    result = run_wrap_regression(str(workspace), str(tmp_path))
    assert result.status == STATUS_BUG_NOT_REPRODUCED
    assert parse_failure_evidence(result) is None


def test_reverify_failure_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JACVERIFY_FORCE_REVERIFY_FAIL", "1")
    workspace = Path(__file__).resolve().parents[1]
    result = run_reverify(str(workspace), str(tmp_path))
    assert result.status == STATUS_VERIFICATION_FAILED


def test_live_mode_without_iverilog_is_tool_error_not_silent_mock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JACVERIFY_MOCK_TOOLS", "0")
    monkeypatch.setenv("PATH", "")
    workspace = Path(__file__).resolve().parents[1]
    result = lint_compile(str(workspace), str(tmp_path))
    assert result.mode == "live"
    assert result.status == STATUS_TOOL_ERROR


def test_legacy_suite_helper_still_works(tmp_path: Path) -> None:
    workspace = Path(__file__).resolve().parents[1]
    evidence = run_fifo_suite(str(workspace), str(tmp_path))
    assert evidence.lint.status == STATUS_PASSED
    assert evidence.smoke.status == STATUS_PASSED
    assert evidence.failing_regression.status == STATUS_VERIFICATION_FAILED
    assert evidence.patched_reverify.status == STATUS_PASSED


def test_upload_matches_curated_fifo_by_content() -> None:
    workspace = Path(__file__).resolve().parents[1]
    buggy = (workspace / "demo" / "fifo" / "fifo_buggy.sv").read_text(encoding="utf-8")
    matched = identify_uploaded_case(str(workspace), "my_fifo.sv", buggy)
    rejected = identify_uploaded_case(str(workspace), "random.sv", "module x; endmodule\n")
    curated = load_curated_case_upload(str(workspace), "fifo")

    assert matched.accepted
    assert matched.case_id == "fifo"
    assert not rejected.accepted
    assert curated.accepted
    assert curated.filename == "fifo_buggy.sv"


@pytest.mark.parametrize(
    ("case_id", "fail_kind", "expected", "observed", "claim_needle", "fixed_name"),
    [
        ("alu", "ALU_MISMATCH", "05", "0b", "sub", "alu_fixed.sv"),
        (
            "shift_reg",
            "SHIFT_MISMATCH",
            "40",
            "00",
            "shift",
            "shift_reg_fixed.sv",
        ),
    ],
)
def test_mock_pipeline_for_sibling_cases(
    case_id: str,
    fail_kind: str,
    expected: str,
    observed: str,
    claim_needle: str,
    fixed_name: str,
    tmp_path: Path,
) -> None:
    workspace = Path(__file__).resolve().parents[1]
    set_active_case(case_id)

    spec = load_spec(str(workspace))
    regression = run_wrap_regression(str(workspace), str(tmp_path / case_id))
    evidence = parse_failure_evidence(regression)
    assert evidence is not None
    hypotheses = rank_hypotheses(evidence)
    artifact = generate_artifact(hypotheses[0], case_id)
    reverify = run_reverify(str(workspace), str(tmp_path / case_id))
    curated = load_curated_case_upload(str(workspace), case_id)
    buggy = (
        workspace / "demo" / case_id / f"{case_id}_buggy.sv"
    ).read_text(encoding="utf-8")
    matched = identify_uploaded_case(str(workspace), f"my_{case_id}.sv", buggy)

    assert spec.requirement_count == 5
    assert spec.module_name == case_id
    assert regression.status == STATUS_VERIFICATION_FAILED
    assert evidence.kind == fail_kind
    assert evidence.expected == expected
    assert evidence.observed == observed
    assert claim_needle in hypotheses[0].claim.lower()
    assert fixed_name in artifact.candidate_path
    assert reverify.status == STATUS_PASSED
    assert curated.accepted
    assert matched.accepted
    assert matched.case_id == case_id

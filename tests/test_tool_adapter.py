import os
from pathlib import Path

import pytest

import jacverify.tool_adapter as tool_adapter
from jacverify.tool_adapter import (
    STATUS_BUG_NOT_REPRODUCED,
    STATUS_PASSED,
    STATUS_TOOL_ERROR,
    STATUS_VERIFICATION_FAILED,
    coverage_from_result,
    generate_artifact,
    identify_uploaded_case,
    identify_uploaded_inputs,
    lint_compile,
    load_curated_case_upload,
    load_spec,
    materialize_uploaded_inputs,
    parse_failure_evidence,
    rank_hypotheses,
    run_fifo_suite,
    run_reverify,
    run_smoke,
    run_wrap_regression,
)


@pytest.fixture(autouse=True)
def _mock_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JACVERIFY_MOCK_TOOLS", "1")
    monkeypatch.setenv("JACVERIFY_MOCK_LLM", "1")
    monkeypatch.delenv("JACVERIFY_FORCE_BUG_NOT_REPRODUCED", raising=False)
    monkeypatch.delenv("JACVERIFY_FORCE_REVERIFY_FAIL", raising=False)


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


def test_mock_reverify_sequence_is_selected_by_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "JACVERIFY_REVERIFY_SEQUENCE",
        "VERIFICATION_FAILED,TOOL_ERROR,PASSED",
    )
    workspace = Path(__file__).resolve().parents[1]

    assert run_reverify(str(workspace), str(tmp_path), 1).status == STATUS_VERIFICATION_FAILED
    assert run_reverify(str(workspace), str(tmp_path), 2).status == STATUS_TOOL_ERROR
    assert run_reverify(str(workspace), str(tmp_path), 3).status == STATUS_PASSED


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


def test_firecrawl_live_adapter_parses_typed_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JACVERIFY_MOCK_LLM", "0")
    monkeypatch.setenv("JACVERIFY_LLM_BACKEND", "firecrawl")
    outputs = iter(
        [
            {
                "hypotheses": [
                    {
                        "rank": 1,
                        "claim": "write_ptr wraps to the wrong slot",
                        "confidence": 0.9,
                        "next_action": "run a directed wrap test",
                    },
                    {
                        "rank": 2,
                        "claim": "read_ptr wrap is incorrect",
                        "confidence": 0.2,
                        "next_action": "inspect read_ptr at DEPTH-1",
                    },
                    {
                        "rank": 3,
                        "claim": "count drifts during concurrent operations",
                        "confidence": 0.1,
                        "next_action": "check simultaneous read/write occupancy",
                    },
                ]
            },
            {
                "kind": "directed_test",
                "description": "Exercise FIFO wraparound twice.",
                "verification_goal": "Preserve ordering across pointer wrap.",
                "rationale": "The sequence isolates pointer rollover behavior.",
            },
        ]
    )
    monkeypatch.setattr(
        tool_adapter,
        "_firecrawl_agent",
        lambda **_: next(outputs),
    )
    regression = run_wrap_regression(".", "/tmp/jacverify-firecrawl-parse")
    failure = parse_failure_evidence(regression)
    assert failure is not None

    hypotheses = rank_hypotheses(failure)
    artifact = generate_artifact(hypotheses[0], "fifo")

    assert hypotheses[0].rank == 1
    assert hypotheses[0].confidence == 0.9
    assert artifact.kind == "firecrawl_directed_test"
    assert artifact.candidate_path == "demo/fifo/fifo_fixed.sv"


def test_firecrawl_live_adapter_requires_local_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JACVERIFY_MOCK_LLM", "0")
    monkeypatch.setenv("JACVERIFY_LLM_BACKEND", "firecrawl")
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="FIRECRAWL_API_KEY is empty"):
        tool_adapter._firecrawl_agent(prompt="test", schema={"type": "object"})


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


def test_design_and_spec_uploads_generate_a_testbench(tmp_path: Path) -> None:
    workspace = Path(__file__).resolve().parents[1]
    design = (workspace / "demo" / "fifo" / "fifo_buggy.sv").read_text(
        encoding="utf-8"
    )
    spec = (workspace / "demo" / "fifo" / "fifo_spec.md").read_text(
        encoding="utf-8"
    )
    generic_design = "module adder; endmodule\n"
    generic_spec = "# Adder requirements\n\nThe output must equal the sum.\n"

    curated = identify_uploaded_inputs(
        str(workspace),
        "design.sv",
        design,
        "fifo_spec.md",
        spec,
    )
    generic = identify_uploaded_inputs(
        str(workspace),
        "adder.sv",
        generic_design,
        "adder_spec.md",
        generic_spec,
    )
    paths = materialize_uploaded_inputs(
        str(workspace),
        str(tmp_path),
        "adder.sv",
        generic_design,
        "adder_spec.md",
        generic_spec,
    )

    assert curated.accepted and curated.case_id == "fifo"
    assert generic.accepted and generic.case_id == "uploaded"
    assert Path(paths.design_path).read_text(encoding="utf-8") == generic_design
    assert Path(paths.spec_path).read_text(encoding="utf-8") == generic_spec
    assert "module tb_wrap" in Path(paths.test_path).read_text(encoding="utf-8")
    assert Path(paths.test_path).name == "generated_tb_wrap.sv"
    assert paths.design_module == "adder"
    assert paths.test_module == "tb_wrap"


def test_coverage_marker_is_parsed_from_test_output(tmp_path: Path) -> None:
    result = run_wrap_regression(".", str(tmp_path))
    coverage = coverage_from_result(result)

    assert coverage.available
    assert coverage.code_coverage == 72.5
    assert coverage.functional_coverage == 66.7
    assert coverage.source == "mock:testbench_marker"

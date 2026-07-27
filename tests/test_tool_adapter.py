import os
import threading
import time
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
    generate_testbench_for_run,
    identify_uploaded_case,
    identify_uploaded_inputs,
    lint_compile,
    load_curated_case_upload,
    load_spec,
    materialize_uploaded_inputs,
    parse_failure_evidence,
    publish_candidate_output,
    rank_hypotheses,
    render_code_diff,
    run_fifo_suite,
    run_reverify,
    run_smoke,
    run_wrap_regression,
    set_active_case,
    text_file_data_url,
)


@pytest.fixture(autouse=True)
def _mock_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JACVERIFY_MOCK_TOOLS", "1")
    monkeypatch.setenv("JACVERIFY_MOCK_LLM", "1")
    monkeypatch.setenv("JACVERIFY_AI_TESTGEN", "0")
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


def test_parse_ai_generated_failure_protocol() -> None:
    result = tool_adapter.rebuild_tool_result(
        tool="vvp",
        mode="live",
        status=STATUS_VERIFICATION_FAILED,
        exit_code=1,
        stdout=(
            "JACVERIFY_FAILURE kind=SUM_MISMATCH "
            "expected=0a observed=09 cycle=7\n"
        ),
    )
    evidence = parse_failure_evidence(result)

    assert evidence is not None
    assert evidence.kind == "SUM_MISMATCH"
    assert evidence.expected == "0a"
    assert evidence.observed == "09"
    assert evidence.cycle == 7


def test_render_code_diff_returns_named_unified_diff(tmp_path: Path) -> None:
    before = tmp_path / "buggy.sv"
    after = tmp_path / "fixed.sv"
    before.write_text("module fifo;\nassign full = 0;\nendmodule\n", encoding="utf-8")
    after.write_text("module fifo;\nassign full = count == 4;\nendmodule\n", encoding="utf-8")

    diff = render_code_diff(
        str(before),
        str(after),
        "fifo_buggy.sv",
        "fifo_fixed.sv",
    )

    assert "--- fifo_buggy.sv" in diff
    assert "+++ fifo_fixed.sv" in diff
    assert "-assign full = 0;" in diff
    assert "+assign full = count == 4;" in diff


def test_publish_candidate_output_copies_allowlisted_file(tmp_path: Path) -> None:
    workspace = Path(__file__).resolve().parents[1]

    published = Path(
        publish_candidate_output(
            str(workspace),
            str(tmp_path),
            "demo/fifo/fifo_fixed.sv",
        )
    )

    assert published == tmp_path / "outputs" / "fifo_fixed.sv"
    assert published.read_text(encoding="utf-8") == (
        workspace / "demo" / "fifo" / "fifo_fixed.sv"
    ).read_text(encoding="utf-8")
    assert text_file_data_url(str(published)).startswith(
        "data:text/plain;charset=utf-8;base64,"
    )


def test_publish_candidate_output_rejects_outside_workspace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.sv"
    outside.write_text("module outside; endmodule\n", encoding="utf-8")

    with pytest.raises(ValueError, match="inside the workspace"):
        publish_candidate_output(
            str(workspace),
            str(tmp_path / "run"),
            str(outside),
        )


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
    generated = generate_testbench_for_run(
        str(workspace),
        str(tmp_path),
        paths.design_path,
        paths.spec_path,
    )

    assert curated.accepted and curated.case_id == "fifo"
    assert generic.accepted and generic.case_id == "uploaded"
    assert Path(paths.design_path).read_text(encoding="utf-8") == generic_design
    assert Path(paths.spec_path).read_text(encoding="utf-8") == generic_spec
    assert paths.test_path == ""
    assert "module tb_wrap" in Path(generated.path).read_text(encoding="utf-8")
    assert generated.filename == "generated_tb_wrap.sv"
    assert generated.mode == "hardcoded:fifo-prototype"
    assert paths.design_module == "adder"
    assert paths.test_module == ""


def test_ai_testgen_writes_typed_firecrawl_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = Path(__file__).resolve().parents[1]
    paths = materialize_uploaded_inputs(
        str(workspace),
        str(tmp_path),
        "adder.sv",
        "module adder; endmodule\n",
        "adder_spec.md",
        "# Adder\nThe design must elaborate.\n",
    )
    monkeypatch.setenv("JACVERIFY_AI_TESTGEN", "1")
    monkeypatch.setenv("JACVERIFY_MOCK_LLM", "0")
    monkeypatch.setenv("JACVERIFY_LLM_BACKEND", "firecrawl")
    monkeypatch.setattr(
        tool_adapter,
        "_firecrawl_agent",
        lambda **_: {
            "testbench": (
                "```systemverilog\n"
                "module generated_adder_test;\n"
                "  adder dut();\n"
                "  initial begin\n"
                '    $display("JACVERIFY_TEST_PASS");\n'
                "    $finish;\n"
                "  end\n"
                "endmodule\n"
                "```"
            ),
            "notes": "Bounded elaboration test.",
        },
    )

    generated = generate_testbench_for_run(
        str(workspace),
        str(tmp_path),
        paths.design_path,
        paths.spec_path,
    )

    assert generated.mode == "ai:firecrawl"
    assert generated.filename == "generated_ai_testbench.sv"
    assert generated.module_name == "generated_adder_test"
    assert "```" not in Path(generated.path).read_text(encoding="utf-8")


def test_ai_testgen_repairs_compile_error_before_returning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = Path(__file__).resolve().parents[1]
    paths = materialize_uploaded_inputs(
        str(workspace),
        str(tmp_path),
        "adder.sv",
        "module adder; endmodule\n",
        "adder_spec.md",
        "# Adder\nThe design must elaborate.\n",
    )
    monkeypatch.setenv("JACVERIFY_AI_TESTGEN", "1")
    monkeypatch.setenv("JACVERIFY_MOCK_LLM", "0")
    monkeypatch.setenv("JACVERIFY_MOCK_TOOLS", "0")
    monkeypatch.setenv("JACVERIFY_AI_TESTGEN_REPAIR_ATTEMPTS", "1")
    responses = iter(
        [
            {
                "testbench": "module tb_adder; initial { $finish; } endmodule",
                "notes": "initial draft",
            },
            {
                "testbench": (
                    "module tb_adder;\n"
                    "  initial begin\n"
                    '    $display("JACVERIFY_TEST_PASS");\n'
                    "    $finish;\n"
                    "  end\n"
                    "endmodule\n"
                ),
                "notes": "repaired draft",
            },
        ]
    )
    monkeypatch.setattr(
        tool_adapter,
        "_firecrawl_agent",
        lambda **_: next(responses),
    )
    compile_calls = 0

    def fake_lint(*_: object) -> tool_adapter.ToolResult:
        nonlocal compile_calls
        compile_calls += 1
        if compile_calls == 1:
            return tool_adapter.ToolResult(
                "iverilog",
                "live",
                tool_adapter.STATUS_TOOL_ERROR,
                2,
                ["iverilog"],
                1,
                "",
                "line 1: syntax error",
            )
        return tool_adapter.ToolResult(
            "iverilog",
            "live",
            tool_adapter.STATUS_PASSED,
            0,
            ["iverilog"],
            1,
            "",
            "",
        )

    monkeypatch.setattr(tool_adapter, "lint_compile", fake_lint)
    generated = generate_testbench_for_run(
        str(workspace),
        str(tmp_path),
        paths.design_path,
        paths.spec_path,
    )

    assert compile_calls == 2
    assert "initial begin" in Path(generated.path).read_text(encoding="utf-8")
    assert "Auto-repaired" in generated.notes


def test_coverage_marker_is_parsed_from_test_output(tmp_path: Path) -> None:
    result = run_wrap_regression(".", str(tmp_path))
    coverage = coverage_from_result(result)

    assert coverage.available
    assert coverage.code_coverage == 72.5
    assert coverage.functional_coverage == 66.7
    assert coverage.source == "mock:testbench_marker"


def test_background_llm_job_starts_without_blocking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = threading.Event()
    draft = tool_adapter.HypothesisDraft(1, "counter wrap", 0.9, "test wrap")
    artifact = tool_adapter.ArtifactDraft(
        "directed_test",
        "exercise counter wrap",
        "demo/fifo/fifo_fixed.sv",
        "fixture",
        draft.claim,
        "test artifact",
    )

    def slow_generate(*_: object) -> tool_adapter.ArtifactDraft:
        assert release.wait(timeout=2)
        return artifact

    monkeypatch.setattr(tool_adapter, "generate_artifact", slow_generate)
    started_at = time.monotonic()
    job_id = tool_adapter.start_artifact_generation_job(draft, "fifo")
    elapsed = time.monotonic() - started_at

    assert elapsed < 0.2
    assert tool_adapter.poll_llm_job(job_id).status in {"queued", "running"}
    release.set()
    deadline = time.monotonic() + 2
    status = tool_adapter.poll_llm_job(job_id)
    while status.status != "completed" and time.monotonic() < deadline:
        time.sleep(0.01)
        status = tool_adapter.poll_llm_job(job_id)

    assert status.status == "completed"
    assert status.artifact == artifact
    tool_adapter.discard_llm_job(job_id)


def test_background_llm_job_retries_after_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    draft = tool_adapter.HypothesisDraft(1, "counter wrap", 0.9, "test wrap")
    artifact = tool_adapter.ArtifactDraft(
        "directed_test",
        "exercise counter wrap",
        "demo/fifo/fifo_fixed.sv",
        "fixture",
        draft.claim,
        "test artifact",
    )

    def flaky_generate(*_: object) -> tool_adapter.ArtifactDraft:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("model exceeded 45s")
        return artifact

    monkeypatch.setenv("JACVERIFY_LLM_RETRIES", "1")
    monkeypatch.setenv("JACVERIFY_LLM_RETRY_DELAY_SECONDS", "0")
    monkeypatch.setattr(tool_adapter, "generate_artifact", flaky_generate)
    job_id = tool_adapter.start_artifact_generation_job(draft, "fifo")
    deadline = time.monotonic() + 2
    status = tool_adapter.poll_llm_job(job_id)
    while status.status not in {"completed", "failed"} and time.monotonic() < deadline:
        time.sleep(0.01)
        status = tool_adapter.poll_llm_job(job_id)

    assert status.status == "completed"
    assert status.attempt == 2
    assert status.max_attempts == 2
    assert calls == 2
    tool_adapter.discard_llm_job(job_id)


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
    design = (workspace / "demo" / case_id / f"{case_id}_buggy.sv").read_text(
        encoding="utf-8"
    )
    case_spec = (workspace / "demo" / case_id / f"{case_id}_spec.md").read_text(
        encoding="utf-8"
    )
    matched = identify_uploaded_inputs(
        str(workspace),
        f"{case_id}_buggy.sv",
        design,
        f"{case_id}_spec.md",
        case_spec,
    )
    paths = materialize_uploaded_inputs(
        str(workspace),
        str(tmp_path / f"{case_id}-inputs"),
        f"{case_id}_buggy.sv",
        design,
        f"{case_id}_spec.md",
        case_spec,
    )
    generated = generate_testbench_for_run(
        str(workspace),
        str(tmp_path / f"{case_id}-inputs"),
        paths.design_path,
        paths.spec_path,
    )

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
    assert matched.accepted and matched.case_id == case_id
    assert paths.test_path == ""
    assert Path(generated.path).name == "generated_tb_directed.sv"
    assert generated.mode == f"hardcoded:{case_id}"

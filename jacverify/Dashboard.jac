"""JacVerify verification workflow UI."""

sv import from .store {
    DemoRunResult,
    TransitionView,
    UploadPreview,
    advance_verification,
    preview_curated_inputs,
    preview_uploaded_inputs,
    start_fifo_demo,
    start_uploaded_inputs,
    wait_for_next_poll,
}

def:pub EvidenceBadge(evidence_kind: str) -> JsxElement {
    label = "TOOL FACT";
    badge_class = "evidence fact";
    if evidence_kind == "model_inference" {
        label = "MODEL INFERENCE";
        badge_class = "evidence inference";
    } elif evidence_kind == "action_recommendation" {
        label = "ACTION";
        badge_class = "evidence recommendation";
    }
    return <span className={badge_class}>{label}</span>;
}

def:pub StatusLabel(status: str) -> JsxElement {
    label = status;
    if status == "VERIFICATION_FAILED" {
        label = "VERIFICATION FAILED";
    } elif status == "TOOL_ERROR" {
        label = "TOOL ERROR";
    } elif status == "BUG_NOT_REPRODUCED" {
        label = "BUG NOT REPRODUCED";
    } elif status == "PASSED" {
        label = "PASSED";
    }
    return <span className={"status-pill " + status.lower()}>{label}</span>;
}

def:pub StageLabel(state: str) -> str {
    if state == "S0_SPEC_INGEST" {
        return "Loading design and specification";
    } elif state == "S2_TEST_GENERATION" {
        return "Generating testbench";
    } elif state == "S3_STATIC_CHECK" {
        return "Compiling generated test";
    } elif state == "S4_COMPILE_ELAB" {
        return "Running simulation";
    } elif state == "D0_FAILURE_NORMALIZE" {
        return "Structuring failure evidence";
    } elif state == "D1_HYPOTHESIS_RANK" {
        return "Ranking hypotheses with AI";
    } elif state == "D3_GENERATE_ARTIFACT" {
        return "Generating verification artifact";
    } elif state == "D4_APPLY_CANDIDATE" {
        return "Re-verifying candidate";
    } elif state == "DONE" {
        return "Verification complete";
    } elif state == "NEEDS_USER_REVIEW" {
        return "User review required";
    } elif state == "BLOCKED" {
        return "Verification blocked";
    }
    return state;
}

def:pub StagePercent(state: str) -> int {
    if state == "S0_SPEC_INGEST" {
        return 5;
    } elif state == "S2_TEST_GENERATION" {
        return 18;
    } elif state == "S3_STATIC_CHECK" {
        return 32;
    } elif state == "S4_COMPILE_ELAB" {
        return 46;
    } elif state == "D0_FAILURE_NORMALIZE" {
        return 60;
    } elif state == "D1_HYPOTHESIS_RANK" {
        return 72;
    } elif state == "D3_GENERATE_ARTIFACT" {
        return 84;
    } elif state == "D4_APPLY_CANDIDATE" {
        return 94;
    } elif state == "DONE" {
        return 100;
    }
    return 100 if state == "NEEDS_USER_REVIEW" or state == "BLOCKED" else 0;
}

def:pub Dashboard -> JsxElement {
    has demo_run: DemoRunResult | None = None,
        running: bool = False,
        error_message: str = "",
        design_filename: str = "",
        design_content: str = "",
        spec_filename: str = "",
        spec_content: str = "",
        upload_preview: UploadPreview | None = None,
        reading_upload: bool = False,
        curated_session: bool = False,
        workflow_started: bool = False;

    async def run_demo;
    async def use_curated_sample;
    async def on_design_file_change(e: any);
    async def on_spec_file_change(e: any);
    def clear_design(_e: MouseEvent);
    def clear_spec(_e: MouseEvent);

    return <div className="app-shell">
        <header className="topbar">
            <div className="brand-lockup">
                <div
                    className="brand-logo"
                    role="img"
                    aria-label="JacVerify"
                ></div>
                <div className="brand-subtitle">Evidence-driven verification loop</div>
            </div>
            <div className="topbar-actions">
                <span className="live-dot"></span>
                <span>Jac graph online</span>
                <a className="repo-link" href="/graph" target="_blank">Inspect graph ↗</a>
            </div>
        </header>

        <main>
            <section className={"hero workflow-intro " + ("is-collapsed" if workflow_started else "")}>
                <div>
                    <div className="eyebrow">VERIFICATION WORKFLOW</div>
                    <h1>Upload a design. Prove it with evidence.</h1>
                    <p className="hero-copy">
                        Jac walkers drive compile, simulation, failure structuring, hypothesis
                        ranking, candidate application, and re-verification—then leave a
                        requirement-to-evidence graph you can inspect.
                    </p>
                </div>
                <div className="hero-proof">
                    <div className="proof-label">JAC AT THE CENTER</div>
                    <div className="proof-flow">
                        Upload <span>→</span> Walkers <span>→</span> Evidence <span>→</span> Reverify
                    </div>
                </div>
            </section>

            {if error_message {
                <div className="error-banner">{error_message}</div>
            }}

            <section className="view-stack">
                <div className={"task-hero workflow-intro " + ("is-collapsed" if workflow_started else "")}>
                    <div>
                        <div className="eyebrow">EIGHT-WALKER EVIDENCE LOOP</div>
                        <h2>Verify a design from its specification</h2>
                        <p>
                            Upload RTL and its requirements. JacVerify generates a testbench,
                            runs it, and records tool evidence and coverage.
                        </p>
                    </div>
                    <button
                        className="run-button"
                        onClick={run_demo}
                        disabled={
                            running
                            or reading_upload
                            or (
                                (not design_content or not spec_content)
                                and not curated_session
                            )
                        }
                        title={
                            "Upload both a design and specification first"
                            if (
                                (not design_content or not spec_content)
                                and not curated_session
                                and not running
                            )
                            else ""
                        }
                    >
                        {
                            "Running walkers…"
                            if running
                            else (
                                "Upload design + spec first"
                                if (
                                    (not design_content or not spec_content)
                                    and not curated_session
                                )
                                else "Run verification loop"
                            )
                        }
                    </button>
                </div>

                <div className="upload-panel">
                    <div className="upload-pair">
                        <label className="upload-drop">
                            <input
                                className="upload-input"
                                type="file"
                                accept=".sv,.v,.vh"
                                onChange={on_design_file_change}
                                disabled={running or reading_upload}
                            />
                            <div className="upload-copy">
                                <div className="eyebrow">1 · DESIGN RTL</div>
                                <h3>
                                    {
                                        design_filename
                                        if design_filename
                                        else "Choose a design file"
                                    }
                                </h3>
                                <p>The module under test. It is stored only in this run.</p>
                            </div>
                        </label>
                        <label className="upload-drop">
                            <input
                                className="upload-input"
                                type="file"
                                accept=".md,.txt,.spec"
                                onChange={on_spec_file_change}
                                disabled={running or reading_upload}
                            />
                            <div className="upload-copy">
                                <div className="eyebrow">2 · SPECIFICATION</div>
                                <h3>
                                    {
                                        spec_filename
                                        if spec_filename
                                        else "Choose a specification file"
                                    }
                                </h3>
                                <p>JacVerify uses this spec to generate the run's testbench.</p>
                            </div>
                        </label>
                    </div>
                    <div className="upload-actions">
                        <button
                            className="secondary-action"
                            onClick={use_curated_sample}
                            disabled={running or reading_upload}
                        >
                            Use curated sample
                        </button>
                        <button
                            className="secondary-action"
                            onClick={clear_design}
                            disabled={running or reading_upload or not design_filename}
                        >
                            Clear design
                        </button>
                        <button
                            className="secondary-action"
                            onClick={clear_spec}
                            disabled={running or reading_upload or not spec_filename}
                        >
                            Clear spec
                        </button>
                    </div>
                    {if upload_preview is not None {
                        <div className={"upload-status " + ("ok" if upload_preview.accepted else "blocked")}>
                            <strong>
                                {
                                    "INPUT PAIR READY · " + upload_preview.case_title
                                    if upload_preview.accepted
                                    else "INPUT PAIR INCOMPLETE"
                                }
                            </strong>
                            <p>{upload_preview.message}</p>
                            <small>{upload_preview.curated_hint}</small>
                        </div>
                    }}
                </div>

                {if demo_run is None {
                    <div className="empty-demo">
                        <div className="empty-icon">⬆</div>
                        <h3>Upload a design and specification to begin</h3>
                        <p>
                            JacVerify generates the testbench in hardcoded or AI mode.
                            Curated fixtures:
                            <code>demo/fifo</code>, <code>demo/alu</code>,
                            <code>demo/shift_reg</code>. Or click
                            <strong>Use curated sample</strong> for the FIFO pair.
                        </p>
                    </div>
                } else {
                    if demo_run.status == "running" {
                        <div className="live-progress">
                            <div className="live-progress-heading">
                                <div>
                                    <div className="eyebrow">LIVE VERIFICATION PROGRESS</div>
                                    <h3>{StageLabel(demo_run.current_state)}</h3>
                                </div>
                                <strong>{StagePercent(demo_run.current_state)}%</strong>
                            </div>
                            <progress
                                max="100"
                                value={StagePercent(demo_run.current_state)}
                            ></progress>
                            <small>
                                Current state: {demo_run.current_state} · completed walkers: {
                                    len(demo_run.walker_log)
                                }
                                {
                                    (
                                        " · LLM job: "
                                        + demo_run.llm_job_status
                                        + " (attempt "
                                        + str(demo_run.llm_job_attempt)
                                        + "/"
                                        + str(demo_run.llm_job_max_attempts)
                                        + ")"
                                    )
                                    if demo_run.llm_job_kind
                                    else ""
                                }
                            </small>
                        </div>
                    }
                    <div className="run-summary">
                        <div>
                            <span>RUN</span>
                            <strong>{demo_run.job_id}</strong>
                        </div>
                        <div>
                            <span>CASE</span>
                            <strong>
                                {
                                    demo_run.case_title
                                    if demo_run.case_title
                                    else "rejected upload"
                                }
                            </strong>
                        </div>
                        <div>
                            <span>DESIGN</span>
                            <strong>
                                {
                                    demo_run.uploaded_filename
                                    if demo_run.uploaded_filename
                                    else "—"
                                }
                            </strong>
                        </div>
                        <div>
                            <span>SPEC</span>
                            <strong>
                                {
                                    demo_run.uploaded_spec_filename
                                    if demo_run.uploaded_spec_filename
                                    else "—"
                                }
                            </strong>
                        </div>
                        <div>
                            <span>GENERATED TEST</span>
                            <strong>
                                {
                                    demo_run.uploaded_test_filename
                                    if demo_run.uploaded_test_filename
                                    else "—"
                                }
                            </strong>
                        </div>
                        <div>
                            <span>FINAL STATE</span>
                            <strong className="done-state">{demo_run.current_state}</strong>
                        </div>
                        <div>
                            <span>TOOL MODE</span>
                            <strong>{demo_run.tool_mode}</strong>
                        </div>
                        <div>
                            <span>LLM MODE</span>
                            <strong>{demo_run.llm_mode}</strong>
                        </div>
                        <div>
                            <span>LLM JOB</span>
                            <strong>
                                {
                                    (
                                        demo_run.llm_job_kind
                                        + " · "
                                        + demo_run.llm_job_status
                                    )
                                    if demo_run.llm_job_kind
                                    else "idle"
                                }
                            </strong>
                        </div>
                        <div>
                            <span>TESTGEN MODE</span>
                            <strong>{demo_run.test_generation_mode}</strong>
                        </div>
                        <div>
                            <span>TESTGEN SOURCE</span>
                            <strong>
                                {
                                    demo_run.test_generation_source
                                    if demo_run.test_generation_source
                                    else "pending"
                                }
                            </strong>
                        </div>
                        <div>
                            <span>DEBUG ATTEMPT</span>
                            <strong>
                                {demo_run.debug_attempt}/{demo_run.max_debug_attempts}
                            </strong>
                        </div>
                    </div>

                    <div className="mode-row">
                        <span>Walkers: {demo_run.walker_log}</span>
                        <a className="repo-link" href={demo_run.graph_hint} target="_blank">
                            Inspect evidence graph ↗
                        </a>
                    </div>

                    <div className="evidence-panel">
                        <div className="evidence-grid">
                            <div>
                                <span>Compile</span>
                                <StatusLabel status={demo_run.compile_status} />
                            </div>
                            <div>
                                <span>Uploaded test</span>
                                <StatusLabel status={demo_run.regression_status} />
                            </div>
                            <div>
                                <span>Re-verify</span>
                                <StatusLabel
                                    status={
                                        "PASSED"
                                        if demo_run.reverify_status == "PASSED"
                                        else demo_run.reverify_status
                                    }
                                />
                                {if demo_run.reverify_status == "PASSED" {
                                    <small>RE-VERIFICATION PASSED</small>
                                }}
                            </div>
                        </div>
                        {if demo_run.failure_kind {
                            <div className="failure-box">
                                <strong>{demo_run.failure_kind}</strong>
                                <div>expected={demo_run.failure_expected}</div>
                                <div>observed={demo_run.failure_observed}</div>
                                {if demo_run.failure_cycle {
                                    <div>cycle={demo_run.failure_cycle}</div>
                                }}
                            </div>
                        }}
                        {if demo_run.top_hypothesis {
                            <div className="hypothesis-box">
                                <div className="eyebrow">
                                    SELECTED HYPOTHESIS · RANK {demo_run.selected_hypothesis_rank}
                                </div>
                                <p>{demo_run.top_hypothesis}</p>
                                <small>confidence={str(demo_run.top_confidence)[:4]} · model inference, not proof</small>
                            </div>
                        }}
                        {if demo_run.artifact_description {
                            <div className="artifact-box">
                                <div className="eyebrow">ARTIFACT / REVIEWED CANDIDATE</div>
                                <p>{demo_run.artifact_description}</p>
                                <small>
                                    {
                                        "candidate applied: " + demo_run.candidate_label
                                        if demo_run.candidate_applied
                                        else "candidate not applied"
                                    }
                                </small>
                            </div>
                        }}
                        {if demo_run.stop_reason {
                            <div className="error-banner">
                                {
                                    "USER REVIEW REQUIRED · " + demo_run.stop_reason
                                    if demo_run.needs_user_review
                                    else demo_run.stop_reason
                                }
                            </div>
                        }}
                    </div>

                    <div className="coverage-panel">
                        <div className="coverage-heading">
                            <div>
                                <div className="eyebrow">LATEST VALIDATION COVERAGE</div>
                                <h3>Coverage reported by the generated test flow</h3>
                            </div>
                            <span className="coverage-source">
                                {
                                    demo_run.coverage_source
                                    if demo_run.coverage_available
                                    else "not reported · N/A"
                                }
                            </span>
                        </div>
                        <div className="coverage-grid">
                            <div className="coverage-card">
                                <div>
                                    <span>CODE COVERAGE</span>
                                    <strong>
                                        {
                                            str(demo_run.code_coverage)[:5] + "%"
                                            if demo_run.coverage_available
                                            else "N/A"
                                        }
                                    </strong>
                                </div>
                                <progress
                                    max="100"
                                    value={
                                        demo_run.code_coverage
                                        if demo_run.coverage_available
                                        else 0
                                    }
                                ></progress>
                            </div>
                            <div className="coverage-card functional">
                                <div>
                                    <span>FUNCTIONAL COVERAGE</span>
                                    <strong>
                                        {
                                            str(demo_run.functional_coverage)[:5] + "%"
                                            if demo_run.coverage_available
                                            else "N/A"
                                        }
                                    </strong>
                                </div>
                                <progress
                                    max="100"
                                    value={
                                        demo_run.functional_coverage
                                        if demo_run.coverage_available
                                        else 0
                                    }
                                ></progress>
                            </div>
                        </div>
                        <small>
                            Optional protocol: print
                            <code>JACVERIFY_COVERAGE code=82.5 functional=75.0</code>
                            from the testbench. Missing values remain N/A.
                        </small>
                    </div>

                    <div className="tool-proof">
                        <div className="tool-proof-heading">
                            <div>
                                <div className="eyebrow">TOOL EVIDENCE</div>
                                <h3>{demo_run.toolchain}</h3>
                                <p className="proof-subline">
                                    {demo_run.requirement_count} requirements · status {demo_run.status}
                                </p>
                            </div>
                            <span className={"proof-status ready" if demo_run.tool_evidence_available else "proof-status blocked"}>
                                {"PIPELINE COMPLETE" if demo_run.tool_evidence_available else "PIPELINE INCOMPLETE"}
                            </span>
                        </div>
                        <div className="terminal-grid">
                            <div className="terminal">
                                <div className="terminal-label failure-output">UPLOADED TEST · INITIAL RUN</div>
                                <pre>{demo_run.regression_output}</pre>
                            </div>
                            <div className="terminal">
                                <div className="terminal-label pass-output">OPTIONAL CANDIDATE · RE-VERIFICATION</div>
                                <pre>{demo_run.reverify_output}</pre>
                            </div>
                        </div>
                    </div>

                    <div className="timeline">
                        {for transition in demo_run.transitions {
                            <article key={transition.sequence} className="timeline-item">
                                <div className="timeline-index">{transition.sequence}</div>
                                <div className="timeline-card">
                                    <div className="timeline-meta">
                                        <span>{transition.from_state}</span>
                                        <span className="arrow">→</span>
                                        <strong>{transition.to_state}</strong>
                                        <EvidenceBadge evidence_kind={transition.evidence_kind} />
                                        {if transition.walker_name {
                                            <span className="evidence-chip">{transition.walker_name}</span>
                                        }}
                                    </div>
                                    <h3>{transition.event}</h3>
                                    <p>{transition.summary}</p>
                                    <div className="evidence-row">
                                        {for evidence_id in transition.evidence_ids {
                                            <span key={evidence_id} className="evidence-chip">{evidence_id}</span>
                                        }}
                                    </div>
                                    {if transition.code_change_content {
                                        <details className="code-change-details">
                                            <summary>
                                                <span>View code change</span>
                                                <span className="code-change-chevron">⌄</span>
                                            </summary>
                                            <div className="code-change-panel">
                                                <div className="code-change-title">
                                                    {transition.code_change_title}
                                                </div>
                                                <pre><code>{transition.code_change_content}</code></pre>
                                            </div>
                                        </details>
                                    }}
                                </div>
                            </article>
                        }}
                    </div>

                    if demo_run.status != "running" and demo_run.output_files {
                        <section className="output-files-panel">
                            <div className="output-files-heading">
                                <div>
                                    <div className="eyebrow">RUN ARTIFACTS</div>
                                    <h3>Output Files</h3>
                                    <p>
                                        Generated files from this verification run.
                                        Review the source or download a local copy.
                                    </p>
                                </div>
                                <span>{len(demo_run.output_files)} FILES</span>
                            </div>
                            <div className="output-files-list">
                                {for output in demo_run.output_files {
                                    <article key={output.filename} className="output-file-card">
                                        <div className="output-file-meta">
                                            <div>
                                                <span>{output.kind}</span>
                                                <strong>{output.filename}</strong>
                                                <small>
                                                    {output.relative_path} · {output.size_bytes} bytes
                                                </small>
                                            </div>
                                        </div>
                                        <details className="output-file-details">
                                            <summary>View</summary>
                                            <div className="code-change-panel output-code-panel">
                                                <div className="code-change-title">
                                                    {output.filename}
                                                </div>
                                                <pre><code>{output.content}</code></pre>
                                            </div>
                                        </details>
                                        <a
                                            className="output-download"
                                            href={output.download_href}
                                            download={output.filename}
                                        >
                                            Download
                                        </a>
                                    </article>
                                }}
                            </div>
                        </section>
                    }
                }}
            </section>
        </main>
    </div>;
}

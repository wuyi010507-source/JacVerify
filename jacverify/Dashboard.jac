"""JacVerify verification workflow UI."""

sv import from .store {
    DemoRunResult,
    TransitionView,
    UploadPreview,
    preview_upload,
    run_fifo_demo,
    run_uploaded_design,
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

def:pub Dashboard -> JsxElement {
    has demo_run: DemoRunResult | None = None,
        running: bool = False,
        error_message: str = "",
        upload_filename: str = "",
        upload_content: str = "",
        upload_preview: UploadPreview | None = None,
        reading_upload: bool = False,
        curated_session: bool = False;

    async def run_demo;
    async def use_curated_sample;
    async def on_file_change(e: any);
    def clear_upload(_e: MouseEvent);

    return <div className="app-shell">
        <header className="topbar">
            <div className="brand-lockup">
                <div className="brand-mark">JV</div>
                <div>
                    <div className="brand-name">JacVerify</div>
                    <div className="brand-subtitle">Evidence-driven verification loop</div>
                </div>
            </div>
            <div className="topbar-actions">
                <span className="live-dot"></span>
                <span>Jac graph online</span>
                <a className="repo-link" href="/graph" target="_blank">Inspect graph ↗</a>
            </div>
        </header>

        <main>
            <section className="hero">
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
                <div className="task-hero">
                    <div>
                        <div className="eyebrow">SEVEN-WALKER EVIDENCE LOOP</div>
                        <h2>Run verification on an uploaded design</h2>
                        <p>
                            Upload RTL to start. Today's runtime executes curated demo cases so
                            the red-to-green path stays reliable; more cases can be allow-listed
                            without changing the walker pipeline.
                        </p>
                    </div>
                    <button
                        className="run-button"
                        onClick={run_demo}
                        disabled={
                            running
                            or reading_upload
                            or (not upload_content and not curated_session)
                        }
                        title={
                            "Upload a design or use a curated sample first"
                            if (not upload_content and not curated_session and not running)
                            else ""
                        }
                    >
                        {
                            "Running walkers…"
                            if running
                            else (
                                "Upload a design first"
                                if (not upload_content and not curated_session)
                                else "Run verification loop"
                            )
                        }
                    </button>
                </div>

                <div className="upload-panel">
                    <label className="upload-drop">
                        <input
                            className="upload-input"
                            type="file"
                            accept=".sv,.v,.vh,.vhd,.md,.txt"
                            onChange={on_file_change}
                            disabled={running or reading_upload}
                        />
                        <div className="upload-copy">
                            <div className="eyebrow">DESIGN UPLOAD</div>
                            <h3>
                                {
                                    "Reading file…"
                                    if reading_upload
                                    else (
                                        upload_filename
                                        if upload_filename
                                        else "Drop or choose an RTL file"
                                    )
                                }
                            </h3>
                            <p>
                                Product path is upload-driven. Hackathon execution is gated to
                                curated cases; unknown designs are rejected explicitly.
                            </p>
                        </div>
                    </label>
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
                            onClick={clear_upload}
                            disabled={running or reading_upload or not upload_filename}
                        >
                            Clear upload
                        </button>
                    </div>
                    {if upload_preview is not None {
                        <div className={"upload-status " + ("ok" if upload_preview.accepted else "blocked")}>
                            <strong>
                                {
                                    "CURATED CASE MATCHED · " + upload_preview.case_title
                                    if upload_preview.accepted
                                    else "UPLOAD NOT IN CURATED SET"
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
                        <h3>Upload a design to begin</h3>
                        <p>
                            For today's demo, upload <code>demo/fifo/fifo_buggy.sv</code> or
                            click <strong>Use curated sample</strong>. Mock mode:
                            JACVERIFY_MOCK_TOOLS=1 JACVERIFY_MOCK_LLM=1.
                        </p>
                    </div>
                } else {
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
                            <span>UPLOAD</span>
                            <strong>
                                {
                                    demo_run.uploaded_filename
                                    if demo_run.uploaded_filename
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
                                <span>Smoke</span>
                                <StatusLabel status={demo_run.smoke_status} />
                            </div>
                            <div>
                                <span>Regression</span>
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
                                <div className="terminal-label failure-output">BUGGY RTL · VERIFICATION FAILED</div>
                                <pre>{demo_run.regression_output}</pre>
                            </div>
                            <div className="terminal">
                                <div className="terminal-label pass-output">REVIEWED FIXTURE · RE-VERIFICATION</div>
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
                                </div>
                            </article>
                        }}
                    </div>
                }}
            </section>
        </main>
    </div>;
}

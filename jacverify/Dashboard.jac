"""JacVerify project and task views."""

sv import from .store {
    DashboardData,
    DemoRunResult,
    PriorityRecommendation,
    TransitionView,
    get_dashboard,
    run_fifo_demo,
}

def:pub SourceBadge(source_kind: str) -> JsxElement {
    label = "REAL + SCENARIO" if source_kind == "mixed" else "SCENARIO";
    badge_class = "badge mixed" if source_kind == "mixed" else "badge scenario";
    return <span className={badge_class}>{label}</span>;
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

def:pub Dashboard -> JsxElement {
    has dashboard: DashboardData | None = None,
        demo_run: DemoRunResult | None = None,
        active_view: str = "project",
        loading: bool = True,
        running: bool = False,
        error_message: str = "";

    async can with entry {
        load_dashboard();
    }

    async def load_dashboard;
    async def run_demo;
    def show_project(_e: MouseEvent);
    def show_task(_e: MouseEvent);

    return <div className="app-shell">
        <header className="topbar">
            <div className="brand-lockup">
                <div className="brand-mark">JV</div>
                <div>
                    <div className="brand-name">JacVerify</div>
                    <div className="brand-subtitle">Evidence-driven verification intelligence</div>
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
                    <div className="eyebrow">PROJECT DECISION LAYER</div>
                    <h1>Know what to verify next.</h1>
                    <p className="hero-copy">
                        JacVerify turns fragmented runs, failures, coverage gaps and budgets
                        into an auditable priority plan—then drives the selected task through
                        a guarded verification loop.
                    </p>
                </div>
                <div className="hero-proof">
                    <div className="proof-label">JAC AT THE CENTER</div>
                    <div className="proof-flow">
                        Graph <span>→</span> Walker <span>→</span> Evidence <span>→</span> Decision
                    </div>
                </div>
            </section>

            <nav className="view-tabs">
                <button
                    className={"tab active" if active_view == "project" else "tab"}
                    onClick={show_project}
                >
                    01 · Project priorities
                </button>
                <button
                    className={"tab active" if active_view == "task" else "tab"}
                    onClick={show_task}
                >
                    02 · FIFO evidence loop
                </button>
            </nav>

            {if error_message {
                <div className="error-banner">{error_message}</div>
            }}

            {if loading {
                <section className="loading-card">
                    <div className="spinner"></div>
                    <p>Traversing the project graph…</p>
                </section>
            } elif dashboard is not None and active_view == "project" {
                <section className="view-stack">
                    <div className="project-heading">
                        <div>
                            <div className="eyebrow">ACTIVE PROJECT</div>
                            <h2>{dashboard.project_name}</h2>
                            <p>{dashboard.milestone}</p>
                        </div>
                        <div className="scenario-label">DEMO SCENARIO DATA</div>
                    </div>

                    <div className="metric-grid">
                        <article className="metric-card alert-card">
                            <div className="metric-label">Failure events</div>
                            <div className="metric-value">{dashboard.failure_events}</div>
                            <div className="metric-foot">Aggregated into 3 root causes</div>
                        </article>
                        <article className="metric-card">
                            <div className="metric-label">Root-cause clusters</div>
                            <div className="metric-value">{dashboard.root_cause_clusters}</div>
                            <div className="metric-foot">One cluster blocks the milestone</div>
                        </article>
                        <article className="metric-card">
                            <div className="metric-label">Functional coverage</div>
                            <div className="metric-value">{dashboard.coverage_percent}%</div>
                            <div className="metric-foot">+0.3% across the last 5 runs</div>
                        </article>
                        <article className="metric-card">
                            <div className="metric-label">Run budget left</div>
                            <div className="metric-value">{dashboard.remaining_budget} h</div>
                            <div className="metric-foot">Cost-aware planning enabled</div>
                        </article>
                    </div>

                    <div className="section-title-row">
                        <div>
                            <div className="eyebrow">TODAY'S PRIORITY PLAN</div>
                            <h2>Three choices. One defensible next move.</h2>
                        </div>
                        <div className="formula">impact × severity × confidence × urgency ÷ cost</div>
                    </div>

                    <div className="recommendation-list">
                        {for recommendation in dashboard.recommendations {
                            <article
                                key={recommendation.target}
                                className={"recommendation top" if recommendation.rank == 1 else "recommendation"}
                            >
                                <div className="rank">0{recommendation.rank}</div>
                                <div className="recommendation-body">
                                    <div className="recommendation-meta">
                                        <span className="target">{recommendation.target}</span>
                                        <SourceBadge source_kind={recommendation.source_kind} />
                                    </div>
                                    <h3>{recommendation.action}</h3>
                                    <p>{recommendation.reason}</p>
                                    <div className="evidence-row">
                                        {for evidence_id in recommendation.evidence_ids {
                                            <span key={evidence_id} className="evidence-chip">{evidence_id}</span>
                                        }}
                                    </div>
                                </div>
                                <div className="score-panel">
                                    <span>PRIORITY SCORE</span>
                                    <strong>{str(recommendation.score)[:5]}</strong>
                                    <small>{recommendation.risk} risk · {recommendation.estimated_cost} h</small>
                                </div>
                            </article>
                        }}
                    </div>

                    <div className="data-note">
                        <strong>Data honesty:</strong> {dashboard.data_note}
                    </div>

                    <button className="primary-action" onClick={show_task}>
                        Execute the top-ranked FIFO action
                        <span>→</span>
                    </button>
                </section>
            } elif dashboard is not None {
                <section className="view-stack">
                    <div className="task-hero">
                        <div>
                            <div className="eyebrow">TASK EXECUTION LAYER</div>
                            <h2>FIFO wraparound verification</h2>
                            <p>
                                One guarded Jac Walker follows evidence through the FSM.
                                High-risk RTL changes remain behind a human gate.
                            </p>
                        </div>
                        <button className="run-button" onClick={run_demo} disabled={running}>
                            {"Running Jac Walker…" if running else "Run evidence loop"}
                        </button>
                    </div>

                    {if demo_run is None {
                        <div className="empty-demo">
                            <div className="empty-icon">▶</div>
                            <h3>Ready to run the core workflow live</h3>
                            <p>
                                The demo will ingest requirements, record a regression failure,
                                rank a hypothesis, choose a bounded action and reverify it.
                            </p>
                        </div>
                    } else {
                        <div className="run-summary">
                            <div>
                                <span>JOB</span>
                                <strong>{demo_run.job_id}</strong>
                            </div>
                            <div>
                                <span>FINAL STATE</span>
                                <strong className="done-state">{demo_run.current_state}</strong>
                            </div>
                            <div>
                                <span>TRANSITIONS</span>
                                <strong>{len(demo_run.transitions)}</strong>
                            </div>
                            <div>
                                <span>STATUS</span>
                                <strong>{demo_run.status}</strong>
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
            }}
        </main>
    </div>;
}

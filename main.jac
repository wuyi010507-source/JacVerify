"""JacVerify full-stack entry point."""

import from jacverify.store {
    DashboardData,
    DemoRunResult,
    PriorityRecommendation,
    TransitionView,
    get_dashboard,
    run_fifo_demo,
}

cl {
    import ".styles.css";
    import from .jacverify.Dashboard { Dashboard }

    def:pub app -> JsxElement {
        return <Dashboard />;
    }
}

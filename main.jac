"""JacVerify full-stack entry point."""

import from jacverify.store {
    DemoRunResult,
    TransitionView,
    UploadPreview,
    advance_verification,
    preview_curated_inputs,
    preview_uploaded_inputs,
    run_fifo_demo,
    run_uploaded_inputs,
    start_fifo_demo,
    start_uploaded_inputs,
    wait_for_next_poll,
}

cl {
    import ".styles.css";
    import from .jacverify.Dashboard { Dashboard }

    def:pub app -> JsxElement {
        return <Dashboard />;
    }
}

"""JacVerify full-stack entry point."""

import from jacverify.store {
    DemoRunResult,
    TransitionView,
    UploadPreview,
    preview_curated_inputs,
    preview_uploaded_inputs,
    run_fifo_demo,
    run_uploaded_inputs,
}

cl {
    import ".styles.css";
    import from .jacverify.Dashboard { Dashboard }

    def:pub app -> JsxElement {
        return <Dashboard />;
    }
}

"""JacVerify full-stack entry point."""

import from jacverify.store {
    DemoRunResult,
    TransitionView,
    UploadPreview,
    preview_upload,
    run_fifo_demo,
    run_uploaded_design,
}

cl {
    import ".styles.css";
    import from .jacverify.Dashboard { Dashboard }

    def:pub app -> JsxElement {
        return <Dashboard />;
    }
}

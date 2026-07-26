"""Client handler implementations for the JacVerify dashboard."""

impl Dashboard.run_demo {
    if not curated_session and not upload_content {
        error_message = "Upload a design file before running the verification loop.";
        return;
    }
    running = True;
    error_message = "";
    try {
        result: DemoRunResult = (
            await run_fifo_demo()
            if curated_session
            else await run_uploaded_design(upload_filename, upload_content)
        );
        demo_run = result;
        if result.status == "blocked" and not result.upload_accepted {
            error_message = result.stop_reason;
        }
    } except Exception as e {
        error_message = "The uploaded design loop failed: " + str(e);
    }
    running = False;
}

impl Dashboard.use_curated_sample {
    running = True;
    error_message = "";
    reading_upload = False;
    curated_session = True;
    try {
        result: DemoRunResult = await run_fifo_demo();
        demo_run = result;
        selected_name = (
            result.uploaded_filename
            if result.uploaded_filename
            else "fifo_buggy.sv"
        );
        upload_filename = selected_name;
        upload_content = "";
        upload_preview = UploadPreview(
            accepted=True,
            case_id=result.case_id,
            case_title=result.case_title,
            message=(
                "Loaded a curated sample through the upload product path. "
                "You can also choose demo/fifo/fifo_buggy.sv from disk."
            ),
            filename=selected_name,
            curated_hint="Curated today: demo/fifo/fifo_buggy.sv"
        );
        if result.status == "blocked" {
            error_message = result.stop_reason;
        }
    } except Exception as e {
        error_message = "Could not load the curated sample: " + str(e);
    }
    running = False;
}

impl Dashboard.on_file_change(e: any) {
    reading_upload = True;
    error_message = "";
    demo_run = None;
    curated_session = False;
    try {
        file_list = e.target.files;
        if file_list is None or file_list.length == 0 {
            reading_upload = False;
            return;
        }
        file = file_list[0];
        # Locals required: Jac/React has-fields update asynchronously.
        selected_name: str = file.name;
        selected_content: str = await file.text();
        preview: UploadPreview = await preview_upload(
            selected_name,
            selected_content
        );
        upload_filename = selected_name;
        upload_content = selected_content;
        upload_preview = preview;
        if preview is not None and not preview.accepted {
            error_message = preview.message;
        }
    } except Exception as err {
        error_message = "Could not read the uploaded file: " + str(err);
        upload_preview = None;
        upload_content = "";
    }
    reading_upload = False;
}

impl Dashboard.clear_upload(_e: MouseEvent) {
    upload_filename = "";
    upload_content = "";
    upload_preview = None;
    demo_run = None;
    error_message = "";
    curated_session = False;
}

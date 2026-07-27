"""Client handler implementations for the JacVerify dashboard."""

impl Dashboard.run_demo {
    if not curated_session and (not design_content or not spec_content) {
        error_message = (
            "Upload both a design file and a specification before running verification."
        );
        return;
    }
    workflow_started = True;
    timeline_open = False;
    running = True;
    error_message = "";
    try {
        result: DemoRunResult = (
            await start_fifo_demo()
            if curated_session
            else await start_uploaded_inputs(
                design_filename,
                design_content,
                spec_filename,
                spec_content
            )
        );
        demo_run = result;
        while result.status == "running" {
            await wait_for_next_poll(450);
            result = await advance_verification(result.job_id);
            demo_run = result;
        }
        if result.status == "blocked" {
            error_message = result.stop_reason;
        }
    } except Exception as e {
        error_message = "The uploaded design loop failed: " + str(e);
    }
    running = False;
}

impl Dashboard.use_curated_sample {
    workflow_started = True;
    timeline_open = False;
    running = True;
    error_message = "";
    reading_upload = False;
    curated_session = True;
    try {
        result: DemoRunResult = await start_fifo_demo();
        preview: UploadPreview = await preview_curated_inputs();
        demo_run = result;
        while result.status == "running" {
            await wait_for_next_poll(450);
            result = await advance_verification(result.job_id);
            demo_run = result;
        }
        design_filename = (
            result.uploaded_filename
            if result.uploaded_filename
            else "fifo_buggy.sv"
        );
        spec_filename = (
            result.uploaded_spec_filename
            if result.uploaded_spec_filename
            else "fifo_spec.md"
        );
        design_content = "";
        spec_content = "";
        upload_preview = preview;
        if result.status == "blocked" {
            error_message = result.stop_reason;
        }
    } except Exception as e {
        error_message = "Could not load the curated sample: " + str(e);
    }
    running = False;
}

impl Dashboard.on_design_file_change(e: any) {
    reading_upload = True;
    error_message = "";
    demo_run = None;
    curated_session = False;
    workflow_started = False;
    try {
        file_list = e.target.files;
        if file_list is None or file_list.length == 0 {
            reading_upload = False;
            return;
        }
        file = file_list[0];
        selected_name: str = file.name;
        selected_content: str = await file.text();
        design_filename = selected_name;
        design_content = selected_content;
        if spec_content {
            preview: UploadPreview = await preview_uploaded_inputs(
                selected_name,
                selected_content,
                spec_filename,
                spec_content
            );
            upload_preview = preview;
            if not preview.accepted {
                error_message = preview.message;
            }
        } else {
            upload_preview = None;
        }
    } except Exception as err {
        error_message = "Could not read the design file: " + str(err);
        upload_preview = None;
        design_content = "";
    }
    reading_upload = False;
}

impl Dashboard.on_spec_file_change(e: any) {
    reading_upload = True;
    error_message = "";
    demo_run = None;
    curated_session = False;
    workflow_started = False;
    try {
        file_list = e.target.files;
        if file_list is None or file_list.length == 0 {
            reading_upload = False;
            return;
        }
        file = file_list[0];
        selected_name: str = file.name;
        selected_content: str = await file.text();
        spec_filename = selected_name;
        spec_content = selected_content;
        if design_content {
            preview: UploadPreview = await preview_uploaded_inputs(
                design_filename,
                design_content,
                selected_name,
                selected_content
            );
            upload_preview = preview;
            if not preview.accepted {
                error_message = preview.message;
            }
        } else {
            upload_preview = None;
        }
    } except Exception as err {
        error_message = "Could not read the specification file: " + str(err);
        upload_preview = None;
        spec_content = "";
    }
    reading_upload = False;
}

impl Dashboard.clear_design(_e: MouseEvent) {
    design_filename = "";
    design_content = "";
    upload_preview = None;
    demo_run = None;
    error_message = "";
    curated_session = False;
    workflow_started = False;
    timeline_open = False;
}

impl Dashboard.clear_spec(_e: MouseEvent) {
    spec_filename = "";
    spec_content = "";
    upload_preview = None;
    demo_run = None;
    error_message = "";
    curated_session = False;
    workflow_started = False;
    timeline_open = False;
}

impl Dashboard.toggle_timeline(_e: MouseEvent) {
    timeline_open = not timeline_open;
}

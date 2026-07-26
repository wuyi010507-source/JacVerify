"""Client handler implementations for the JacVerify dashboard."""

impl Dashboard.run_demo {
    if not curated_session and (not design_content or not test_content) {
        error_message = (
            "Upload both a design file and a testbench before running verification."
        );
        return;
    }
    running = True;
    error_message = "";
    try {
        result: DemoRunResult = (
            await run_fifo_demo()
            if curated_session
            else await run_uploaded_inputs(
                design_filename,
                design_content,
                test_filename,
                test_content
            )
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
        preview: UploadPreview = await preview_curated_inputs();
        demo_run = result;
        design_filename = (
            result.uploaded_filename
            if result.uploaded_filename
            else "fifo_buggy.sv"
        );
        test_filename = (
            result.uploaded_test_filename
            if result.uploaded_test_filename
            else "tb_wrap.sv"
        );
        design_content = "";
        test_content = "";
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
        if test_content {
            preview: UploadPreview = await preview_uploaded_inputs(
                selected_name,
                selected_content,
                test_filename,
                test_content
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

impl Dashboard.on_test_file_change(e: any) {
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
        selected_name: str = file.name;
        selected_content: str = await file.text();
        test_filename = selected_name;
        test_content = selected_content;
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
        error_message = "Could not read the testbench file: " + str(err);
        upload_preview = None;
        test_content = "";
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
}

impl Dashboard.clear_test(_e: MouseEvent) {
    test_filename = "";
    test_content = "";
    upload_preview = None;
    demo_run = None;
    error_message = "";
    curated_session = False;
}

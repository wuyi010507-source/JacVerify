"""Client handler implementations for the JacVerify dashboard."""

impl Dashboard.load_dashboard {
    try {
        dashboard = await get_dashboard();
        loading = False;
    } except Exception as e {
        error_message = "Could not load the Jac project graph: " + str(e);
        loading = False;
    }
}

impl Dashboard.run_demo {
    running = True;
    error_message = "";
    try {
        demo_run = await run_fifo_demo();
    } except Exception as e {
        error_message = "The FIFO evidence loop failed: " + str(e);
    }
    running = False;
}

impl Dashboard.show_project(_e: MouseEvent) {
    active_view = "project";
}

impl Dashboard.show_task(_e: MouseEvent) {
    active_view = "task";
}

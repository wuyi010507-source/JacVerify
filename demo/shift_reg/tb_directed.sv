module tb_directed;
    logic clk = 0;
    logic rst_n = 0;
    logic load = 0;
    logic shift = 0;
    logic serial_in = 0;
    logic [7:0] parallel_in = 0;
    logic [7:0] q;

    shift_reg dut (
        .clk,
        .rst_n,
        .load,
        .shift,
        .serial_in,
        .parallel_in,
        .q
    );

    always #5 clk = ~clk;

    initial begin
        repeat (2) @(posedge clk);
        rst_n <= 1;
        @(posedge clk);

        parallel_in <= 8'b1000_0000;
        load <= 1;
        @(posedge clk);
        load <= 0;
        @(posedge clk);

        // Right-shift once with serial_in=0: expect 0100_0000.
        serial_in <= 1'b0;
        shift <= 1;
        @(posedge clk);
        shift <= 0;
        @(posedge clk);

        if (q !== 8'b0100_0000) begin
            $display(
                "SHIFT_MISMATCH expected=40 observed=%02h",
                q
            );
            $fatal(1);
        end

        // Right-shift with serial_in=1: expect 1010_0000.
        serial_in <= 1'b1;
        shift <= 1;
        @(posedge clk);
        shift <= 0;
        @(posedge clk);

        if (q !== 8'b1010_0000) begin
            $display(
                "SHIFT_MISMATCH expected=A0 observed=%02h",
                q
            );
            $fatal(1);
        end

        $display("SHIFT_TEST_PASS");
        $finish;
    end
endmodule

module tb_smoke;
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

        parallel_in <= 8'hA5;
        load <= 1;
        @(posedge clk);
        load <= 0;
        @(posedge clk);

        if (q !== 8'hA5) begin
            $display("SMOKE_MISMATCH expected=A5 observed=%02h", q);
            $fatal(1);
        end
        $display("SMOKE_TEST_PASS");
        $finish;
    end
endmodule

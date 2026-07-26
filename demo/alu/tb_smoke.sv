module tb_smoke;
    logic clk = 0;
    logic rst_n = 0;
    logic [1:0] opcode = 2'b00;
    logic [7:0] a = 0;
    logic [7:0] b = 0;
    logic [7:0] result;
    logic zero;

    alu dut (
        .clk,
        .rst_n,
        .opcode,
        .a,
        .b,
        .result,
        .zero
    );

    always #5 clk = ~clk;

    initial begin
        repeat (2) @(posedge clk);
        rst_n <= 1;
        @(posedge clk);

        opcode <= 2'b00;
        a <= 8'h02;
        b <= 8'h03;
        @(posedge clk);
        @(posedge clk);

        if (result !== 8'h05) begin
            $display("SMOKE_MISMATCH expected=05 observed=%02h", result);
            $fatal(1);
        end
        $display("SMOKE_TEST_PASS");
        $finish;
    end
endmodule

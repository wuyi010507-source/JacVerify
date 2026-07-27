module tb_directed;
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

    task automatic apply_and_check(
        input logic [1:0] op,
        input logic [7:0] av,
        input logic [7:0] bv,
        input logic [7:0] expected
    );
        begin
            opcode <= op;
            a <= av;
            b <= bv;
            @(posedge clk);
            @(posedge clk);
            if (result !== expected) begin
                $display(
                    "ALU_MISMATCH expected=%02h observed=%02h",
                    expected,
                    result
                );
                $fatal(1);
            end
        end
    endtask

    initial begin
        repeat (2) @(posedge clk);
        rst_n <= 1;
        @(posedge clk);

        apply_and_check(2'b00, 8'h10, 8'h01, 8'h11);
        apply_and_check(2'b01, 8'h08, 8'h03, 8'h05);
        apply_and_check(2'b10, 8'hF0, 8'h3C, 8'h30);
        apply_and_check(2'b11, 8'h0F, 8'h33, 8'h3F);

        $display("ALU_TEST_PASS");
        $finish;
    end
endmodule

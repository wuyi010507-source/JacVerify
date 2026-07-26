module tb_smoke;
    logic clk = 0;
    logic rst_n = 0;
    logic write_en = 0;
    logic [7:0] write_data = 0;
    logic read_en = 0;
    logic [7:0] read_data;
    logic full;
    logic empty;

    fifo dut (
        .clk,
        .rst_n,
        .write_en,
        .write_data,
        .read_en,
        .read_data,
        .full,
        .empty
    );

    always #5 clk = ~clk;

    initial begin
        repeat (2) @(posedge clk);
        rst_n <= 1;
        @(posedge clk);

        write_data <= 8'hA5;
        write_en <= 1;
        @(posedge clk);
        write_en <= 0;
        @(posedge clk);

        if (read_data !== 8'hA5) begin
            $display("SMOKE_MISMATCH expected=A5 observed=%02h", read_data);
            $fatal(1);
        end
        read_en <= 1;
        @(posedge clk);
        read_en <= 0;
        $display("SMOKE_TEST_PASS");
        $finish;
    end
endmodule


module tb_wrap;
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

    task automatic push(input logic [7:0] value);
        begin
            write_data <= value;
            write_en <= 1;
            @(posedge clk);
            write_en <= 0;
            @(posedge clk);
        end
    endtask

    task automatic pop_and_check(input logic [7:0] expected);
        begin
            if (read_data !== expected) begin
                $display(
                    "WRAP_MISMATCH expected=%02h observed=%02h",
                    expected,
                    read_data
                );
                $fatal(1);
            end
            read_en <= 1;
            @(posedge clk);
            read_en <= 0;
            @(posedge clk);
        end
    endtask

    initial begin
        repeat (2) @(posedge clk);
        rst_n <= 1;
        @(posedge clk);

        push(8'h11);
        push(8'h22);
        push(8'h33);
        push(8'h44);
        pop_and_check(8'h11);
        pop_and_check(8'h22);
        push(8'h55);
        push(8'h66);
        pop_and_check(8'h33);
        pop_and_check(8'h44);
        pop_and_check(8'h55);
        pop_and_check(8'h66);

        $display("WRAP_TEST_PASS");
        $finish;
    end
endmodule

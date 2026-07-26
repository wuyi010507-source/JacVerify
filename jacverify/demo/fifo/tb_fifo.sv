`timescale 1ns/1ps
module tb_fifo;
  localparam int DEPTH = 4;
  logic clk = 0, rst_n = 0, wr_en = 0, rd_en = 0;
  logic [7:0] wdata = 0, rdata;
  logic full, empty;
  int accepted = 0, drained = 0, errors = 0;

  fifo #(.DEPTH(DEPTH)) dut (.*);
  always #5 clk = ~clk;

  initial begin
    $dumpfile("fifo.vcd"); $dumpvars(0, tb_fifo);
    repeat (2) @(posedge clk); rst_n = 1;

    // REQ-3: FIFO must accept DEPTH entries before asserting full.
    for (int i = 0; i < DEPTH; i++) begin
      @(negedge clk);
      if (!full) begin wr_en = 1; wdata = 8'hA0 + i; accepted++; end
      else       begin wr_en = 0; $display("[TB] full asserted early after %0d writes", accepted); end
      @(posedge clk); #1 wr_en = 0;
    end

    if (accepted != DEPTH) begin
      errors++;
      $display("[SCOREBOARD] MISMATCH: expected capacity=%0d, accepted=%0d", DEPTH, accepted);
    end

    while (!empty) begin
      @(negedge clk); rd_en = 1; @(posedge clk); #1 rd_en = 0; drained++;
    end
    $display("[TB] drained=%0d", drained);

    if (errors) $display("[RESULT] FAIL errors=%0d", errors);
    else        $display("[RESULT] PASS");
    $finish;
  end
endmodule

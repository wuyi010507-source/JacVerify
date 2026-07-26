// Sync FIFO with the classic "missing wrap bit" defect (JacVerify demo DUT)
module fifo #(parameter int DEPTH = 4, parameter int W = 8) (
    input  logic         clk,
    input  logic         rst_n,
    input  logic         wr_en,
    input  logic [W-1:0] wdata,
    output logic         full,
    input  logic         rd_en,
    output logic [W-1:0] rdata,
    output logic         empty
);
  localparam int AW = $clog2(DEPTH);

  // BUG: pointers lack the extra wrap bit, so full/empty cannot be
  // distinguished across a wrap and usable capacity degrades to DEPTH-1.
  logic [AW-1:0] wptr, rptr;
  logic [W-1:0]  mem [DEPTH];

  assign empty = (wptr == rptr);
  assign full  = ((wptr + 1'b1) == rptr);

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      wptr <= '0;
      rptr <= '0;
    end else begin
      if (wr_en && !full) begin
        mem[wptr] <= wdata;
        wptr      <= wptr + 1'b1;
      end
      if (rd_en && !empty) rptr <= rptr + 1'b1;
    end
  end

  assign rdata = mem[rptr];
endmodule

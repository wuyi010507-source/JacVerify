module shift_reg #(
    parameter int WIDTH = 8
) (
    input  logic             clk,
    input  logic             rst_n,
    input  logic             load,
    input  logic             shift,
    input  logic             serial_in,
    input  logic [WIDTH-1:0] parallel_in,
    output logic [WIDTH-1:0] q
);
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            q <= '0;
        end else if (load) begin
            q <= parallel_in;
        end else if (shift) begin
            // Deliberate demo bug: shifts left instead of right.
            // Correct right-shift would be: q <= {serial_in, q[WIDTH-1:1]};
            q <= {q[WIDTH-2:0], serial_in};
        end
    end
endmodule

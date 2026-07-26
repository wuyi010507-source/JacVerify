module alu #(
    parameter int WIDTH = 8
) (
    input  logic             clk,
    input  logic             rst_n,
    input  logic [1:0]       opcode,
    input  logic [WIDTH-1:0] a,
    input  logic [WIDTH-1:0] b,
    output logic [WIDTH-1:0] result,
    output logic             zero
);
    // opcode: 00=ADD, 01=SUB, 10=AND, 11=OR
    logic [WIDTH-1:0] next_result;

    always_comb begin
        unique case (opcode)
            2'b00: next_result = a + b;
            2'b01: next_result = a - b;
            2'b10: next_result = a & b;
            2'b11: next_result = a | b;
            default: next_result = result;
        endcase
    end

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            result <= '0;
            zero <= 1'b1;
        end else begin
            result <= next_result;
            zero <= (next_result == '0);
        end
    end
endmodule

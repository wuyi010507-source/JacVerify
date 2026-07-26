module fifo #(
    parameter int WIDTH = 8,
    parameter int DEPTH = 4
) (
    input  logic             clk,
    input  logic             rst_n,
    input  logic             write_en,
    input  logic [WIDTH-1:0] write_data,
    input  logic             read_en,
    output logic [WIDTH-1:0] read_data,
    output logic             full,
    output logic             empty
);
    localparam int PTR_W = $clog2(DEPTH);
    logic [WIDTH-1:0] memory [0:DEPTH-1];
    logic [PTR_W-1:0] write_ptr;
    logic [PTR_W-1:0] read_ptr;
    logic [$clog2(DEPTH+1)-1:0] count;

    assign read_data = memory[read_ptr];
    assign full = count == DEPTH;
    assign empty = count == 0;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            write_ptr <= '0;
            read_ptr <= '0;
            count <= '0;
        end else begin
            if (write_en && !full) begin
                memory[write_ptr] <= write_data;
                // Deliberate demo bug: wrap skips slot zero.
                write_ptr <= (write_ptr == DEPTH-1) ? 1 : write_ptr + 1'b1;
            end
            if (read_en && !empty) begin
                read_ptr <= (read_ptr == DEPTH-1) ? '0 : read_ptr + 1'b1;
            end
            case ({write_en && !full, read_en && !empty})
                2'b10: count <= count + 1'b1;
                2'b01: count <= count - 1'b1;
                default: count <= count;
            endcase
        end
    end
endmodule


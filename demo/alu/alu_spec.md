# ALU verification requirements

- REQ-RESET: After reset, `result` and `zero` must be cleared.
- REQ-ADD: Opcode ADD must compute `a + b` (wrap on overflow).
- REQ-SUB: Opcode SUB must compute `a - b` (wrap on underflow).
- REQ-AND: Opcode AND must compute bitwise `a & b`.
- REQ-OR: Opcode OR must compute bitwise `a | b`.

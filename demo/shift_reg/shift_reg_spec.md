# Shift register verification requirements

- REQ-RESET: Reset must clear the register to all zeros.
- REQ-LOAD: When `load` is asserted, `q` must capture `parallel_in` on the next clock.
- REQ-SHIFT: When `shift` is asserted (and not loading), the register must shift right by one bit.
- REQ-SERIAL: On a right shift, `serial_in` must enter the MSB.
- REQ-HOLD: When neither `load` nor `shift` is asserted, `q` must hold its value.

# FIFO verification requirements

- REQ-RESET: Reset must leave the FIFO empty and ready to accept a write.
- REQ-ORDER: Values must be read in the same order in which they were accepted.
- REQ-FULL: The FIFO must accept exactly `DEPTH` entries before asserting `full`.
- REQ-EMPTY: A read while `empty` must not advance the read pointer.
- REQ-CONCURRENT: A simultaneous accepted read and write must preserve occupancy.

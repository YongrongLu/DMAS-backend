"""Middleware constants

Constants provided:
- EGRESS_MAX_CHARS:             max chars of a department conclusion leaving the device   default 6000
- EGRESS_MAX_ID_HITS:           restricted identifiers that block the whole conclusion    default 3
- EGRESS_MAX_TABLE_LINES:       raw CSV-like lines that count as a data dump              default 30
- EGRESS_REDACTED:              replacement for a redacted identifier
"""

# egress_guard.py
EGRESS_MAX_CHARS = 6000
EGRESS_MAX_ID_HITS = 3
EGRESS_MAX_TABLE_LINES = 30
EGRESS_REDACTED = "[REDACTED]"

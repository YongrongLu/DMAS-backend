"""Distributed runtime constants

Constants provided:
- PING_INTERVAL_SECONDS:        WebSocket keepalive interval                        default 20s
- PING_TIMEOUT_SECONDS:         no pong within this window = connection lost        default 60s
- REGISTER_TIMEOUT_SECONDS:     max wait for the register frame after connecting    default 10s
- RECONNECT_DELAY_SECONDS:      agent retry interval while the hub is down          default 2s
- MAX_FRAME_BYTES:              largest frame accepted                              default 1 MB
"""

PING_INTERVAL_SECONDS = 20
PING_TIMEOUT_SECONDS = 60
REGISTER_TIMEOUT_SECONDS = 10
RECONNECT_DELAY_SECONDS = 2
MAX_FRAME_BYTES = 1 << 20

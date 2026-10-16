"""UUID helpers compatible with the project's minimum Python version."""

import secrets
import time
import uuid


def uuid7() -> uuid.UUID:
    """Generate an RFC 9562 UUIDv7 using a millisecond timestamp and random bits."""
    timestamp_ms = time.time_ns() // 1_000_000
    random_a = secrets.randbits(12)
    random_b = secrets.randbits(62)
    value = (
        ((timestamp_ms & ((1 << 48) - 1)) << 80)
        | (0x7 << 76)
        | (random_a << 64)
        | (0b10 << 62)
        | random_b
    )
    return uuid.UUID(int=value)
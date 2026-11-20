"""Bounded framing and operation filtering, not SSH cryptography."""

import struct

MAX_FRAME = 256 * 1024
IDENTITIES = 11
SIGN = 13
EXTENSION = 27
FAILURE = b"\x05"


def string(value: bytes) -> bytes:
    return struct.pack(">I", len(value)) + value


class Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    def take(self, length: int) -> bytes:
        if length < 0 or self.offset + length > len(self.data):
            raise ValueError("Invalid SSH-agent frame")
        value = self.data[self.offset : self.offset + length]
        self.offset += length
        return value

    def string(self) -> bytes:
        length = struct.unpack(">I", self.take(4))[0]
        return self.take(length)

    def finish(self) -> None:
        if self.offset != len(self.data):
            raise ValueError("Unexpected SSH-agent data")


def validate_request(data: bytes) -> tuple[int, bytes | None]:
    if not data or len(data) > MAX_FRAME:
        raise ValueError("Invalid SSH-agent frame size")
    reader = Reader(data)
    operation = reader.take(1)[0]
    key = None
    if operation == IDENTITIES:
        pass
    elif operation == SIGN:
        key = reader.string()
        reader.string()
        flags = struct.unpack(">I", reader.take(4))[0]
        if flags not in (0, 2, 4):
            raise ValueError("Unsupported signature flags")
    elif operation == EXTENSION:
        if reader.string() != b"session-bind@openssh.com":
            raise ValueError("Unsupported extension")
        key = reader.string()
        reader.string()
        reader.string()
        # Only first-hop authentication is supported; no forwarded agent chains.
        if reader.take(1) != b"\x00":
            raise ValueError("Forwarding is not supported")
    else:
        raise ValueError("Unsupported SSH-agent operation")
    reader.finish()
    return operation, key

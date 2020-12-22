from __future__ import annotations

from src.types.buffer import Buffer


class Packet(Buffer):
    """Base packet class."""

    def __init__(self, id: int, buf: bytes = None, comp_thresh: int = -1):
        Buffer.__init__(self, buf)

        self.id = -0x1
        self.comp_thresh = comp_thresh

    @classmethod
    def from_bytes(cls, data: bytes, comp_thresh: int = -1) -> Packet:
        out = Buffer.from_bytes(data, comp_thresh)

        self.id = self.unpack_varint()
        self.compression_threshold = comp_thresh

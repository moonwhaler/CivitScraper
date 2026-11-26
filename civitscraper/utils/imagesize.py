"""
Pixel size of JPEG, PNG and WEBP files from their headers.

Used to check that an existing preview file really shows the image its sidecar
entry describes, without depending on an imaging library.
"""

import struct
from typing import BinaryIO, Optional, Tuple

Size = Tuple[int, int]


def _jpeg(f: BinaryIO) -> Optional[Size]:
    f.seek(2)
    while True:
        marker = f.read(2)
        if len(marker) < 2 or marker[0] != 0xFF:
            return None
        code = marker[1]
        if code in (0xD8, 0x01) or 0xD0 <= code <= 0xD7:  # markers without a length
            continue
        length_bytes = f.read(2)
        if len(length_bytes) < 2:
            return None
        length = struct.unpack(">H", length_bytes)[0]
        # Start-of-frame markers carry the size (not DHT C4, JPG C8, DAC CC)
        if 0xC0 <= code <= 0xCF and code not in (0xC4, 0xC8, 0xCC):
            data = f.read(5)
            if len(data) < 5:
                return None
            height, width = struct.unpack(">HH", data[1:5])
            return width, height
        f.seek(length - 2, 1)


def _png(header: bytes) -> Optional[Size]:
    if len(header) >= 24 and header[12:16] == b"IHDR":
        width, height = struct.unpack(">II", header[16:24])
        return width, height
    return None


def _webp(f: BinaryIO) -> Optional[Size]:
    f.seek(12)
    chunk = f.read(4)
    data = f.read(26)
    if chunk == b"VP8X" and len(data) >= 14:
        width = 1 + int.from_bytes(data[8:11], "little")
        height = 1 + int.from_bytes(data[11:14], "little")
        return width, height
    if chunk == b"VP8 " and len(data) >= 14 and data[7:10] == b"\x9d\x01\x2a":
        width, height = struct.unpack("<HH", data[10:14])
        return width & 0x3FFF, height & 0x3FFF
    if chunk == b"VP8L" and len(data) >= 9 and data[4] == 0x2F:
        bits = int.from_bytes(data[5:9], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    return None


def image_size(path: str) -> Optional[Size]:
    """
    Return ``(width, height)`` of a JPEG, PNG or WEBP file.

    Args:
        path: Image file

    Returns:
        The size, or None for other formats, damaged files or read errors
    """
    try:
        with open(path, "rb") as f:
            header = f.read(32)
            if header[:3] == b"\xff\xd8\xff":
                return _jpeg(f)
            if header[:8] == b"\x89PNG\r\n\x1a\n":
                return _png(header)
            if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
                return _webp(f)
    except (OSError, struct.error):
        return None
    return None

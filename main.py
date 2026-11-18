#!/usr/bin/env python3
"""World Brief — make.fun news-image-20261118 entry runtime.

Copies the committed entry.png (a self-contained infographic of
18 November 2026 world news) to the grader's output directory:
$MAKEFUN_OUTPUT_DIR/entry.png if set, else /output/entry.png.
A development output directory may be passed as argv[1].

Standard library only, offline, deterministic: both runs write
identical bytes because the source image is read from the repository.
Before writing it validates the PNG is complete (signature, chunk CRCs,
full zlib pixel-data decode) and within the competition limits.
"""

import os
import struct
import sys
import zlib
from pathlib import Path

MAX_BYTES = 1048576  # 1 MiB
MAX_DIM = 1024


def validate_png(data: bytes) -> tuple[int, int]:
    """Check a whole PNG: signature, chunk CRCs, zlib stream, size limits.

    Returns (width, height). Raises ValueError with a human-readable reason.
    """
    if len(data) > MAX_BYTES:
        raise ValueError(f"entry.png is {len(data)} bytes, over the {MAX_BYTES} limit")
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("entry.png lacks the PNG signature")
    offset, ihdr = 8, None
    idat = bytearray()
    while offset < len(data):
        if offset + 8 > len(data):
            raise ValueError("truncated chunk header")
        (length, ctype) = struct.unpack(">I4s", data[offset:offset + 8])
        chunk_end = offset + 8 + length + 4
        if chunk_end > len(data):
            raise ValueError(f"chunk {ctype!r} runs past end of file")
        (crc,) = struct.unpack(">I", data[chunk_end - 4:chunk_end])
        if crc != zlib.crc32(data[offset + 4:offset + 8 + length]) & 0xFFFFFFFF:
            raise ValueError(f"chunk {ctype!r} fails its CRC")
        if ctype == b"IHDR":
            width, height = struct.unpack(">II", data[offset + 8:offset + 16])
            ihdr = (width, height, data[offset + 16], data[offset + 17])
        elif ctype == b"IDAT":
            idat += data[offset + 8:offset + 8 + length]
        elif ctype == b"IEND":
            break
        offset = chunk_end
    if ihdr is None:
        raise ValueError("no IHDR chunk")
    width, height, _depth, _color = ihdr
    if width > MAX_DIM or height > MAX_DIM:
        raise ValueError(f"entry.png is {width}x{height}, over {MAX_DIM}x{MAX_DIM}")
    # The image data must decompress in full to prove the file is whole.
    decompressor = zlib.decompressobj()
    decompressor.decompress(bytes(idat))
    decompressor.flush()
    if not decompressor.eof:
        raise ValueError("zlib pixel data is incomplete")
    return width, height


def resolve_output_dir(argv: list[str], env: dict[str, str]) -> Path:
    """Output directory precedence: argv[1] dev path, then $MAKEFUN_OUTPUT_DIR, then /output."""
    if len(argv) > 1:
        return Path(argv[1])
    return Path(env.get("MAKEFUN_OUTPUT_DIR") or "/output")


def main() -> int:
    src = Path(__file__).resolve().parent / "entry.png"
    data = src.read_bytes()
    width, height = validate_png(data)
    out_dir = resolve_output_dir(sys.argv, os.environ)
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / "entry.png"
    dst.write_bytes(data)
    print(f"wrote {dst} ({len(data)} bytes, {width}x{height})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

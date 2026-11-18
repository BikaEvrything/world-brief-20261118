#!/usr/bin/env python3
"""Runtime entry point for the "World Brief — Daily Signals" news image.

Deterministic, offline, standard library only:
  * reads the committed entry.png from the repository root,
  * verifies the PNG header (signature, size, dimensions),
  * writes those exact bytes to the output location.

Output location (first match wins):
  1. --output PATH            (command line, useful for testing)
  2. $MAKEFUN_OUTPUT_DIR      (environment)
  3. /output/entry.png        (grading default)

No network access, no browser, no third-party packages are required or used.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
import tempfile
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
SOURCE_PNG = REPO_ROOT / "entry.png"

DEFAULT_OUTPUT_DIR = "/output"
DEFAULT_OUTPUT_NAME = "entry.png"

MAX_BYTES = 1024 * 1024  # 1 MiB
MAX_DIM = 1024  # hard cap in either dimension

EXPECTED_WIDTH = 1024
EXPECTED_HEIGHT = 960

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class OutputError(RuntimeError):
    pass


def read_committed_png(path: Path = SOURCE_PNG) -> bytes:
    """Load the committed PNG bytes and validate the container end to end."""
    if not path.is_file():
        raise OutputError(f"committed image not found: {path}")
    data = path.read_bytes()
    if len(data) > MAX_BYTES:
        raise OutputError(f"image exceeds 1 MiB: {len(data)} bytes")
    verify_png(data)
    return data


def verify_png(data: bytes) -> None:
    """Full structural check of a PNG byte stream.

    Enforces the PNG spec's mandatory chunk order:
      * signature, then IHDR as the very first chunk (exactly once),
      * at least one IDAT chunk,
      * exactly one IEND chunk terminating the file, with no chunks after it,
    plus CRC integrity, the 1 MiB size cap and expected dimensions.
    """
    if not data.startswith(PNG_SIGNATURE):
        raise OutputError("not a PNG file (bad signature)")
    if len(data) < 8 + 12 + 12:  # signature + IHDR + IEND minimum
        raise OutputError("PNG too short to be valid")

    ihdr: bytes | None = None
    idat_count = 0
    iend_seen = False
    first = True  # nothing parsed yet, so the next chunk must be IHDR
    offset = 8
    while offset < len(data):
        if offset + 8 > len(data):
            raise OutputError("truncated PNG chunk header")
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        ctype = data[offset + 4 : offset + 8]
        chunk_start = offset + 8
        chunk_end = chunk_start + length
        if chunk_end + 4 > len(data):
            raise OutputError("truncated PNG chunk body")
        body = data[chunk_start:chunk_end]
        (crc,) = struct.unpack(">I", data[chunk_end : chunk_end + 4])
        if zlib.crc32(ctype + body) & 0xFFFFFFFF != crc:
            raise OutputError(f"PNG chunk CRC mismatch in {ctype!r}")

        if ctype == b"IHDR":
            if ihdr is not None:
                raise OutputError("duplicate IHDR chunk")
            if not first:
                raise OutputError("IHDR must be the first chunk")
            ihdr = body
        elif ctype == b"IDAT":
            idat_count += 1
        elif ctype == b"IEND":
            if chunk_end + 4 != len(data):
                raise OutputError("chunks follow IEND; IEND must terminate the file")
            iend_seen = True
            break
        first = False
        offset = chunk_end + 4

    if not iend_seen:
        raise OutputError("PNG missing IEND chunk")
    if ihdr is None or len(ihdr) != 13:
        raise OutputError("PNG missing valid IHDR")
    if idat_count < 1:
        raise OutputError("PNG missing IDAT chunk(s)")
    width, height = struct.unpack(">II", ihdr[0:8])
    if width > MAX_DIM or height > MAX_DIM:
        raise OutputError(f"dimensions exceed {MAX_DIM}px: {width}x{height}")
    if (width, height) != (EXPECTED_WIDTH, EXPECTED_HEIGHT):
        raise OutputError(f"unexpected dimensions {width}x{height}")


def resolve_output_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "").strip()
    if env_dir:
        return Path(env_dir).expanduser() / DEFAULT_OUTPUT_NAME
    return Path(DEFAULT_OUTPUT_DIR) / DEFAULT_OUTPUT_NAME


def write_output(data: bytes, destination: Path) -> None:
    parent = destination.parent
    if not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)
    # atomic write: temp file in the destination directory, then replace
    fd, tmp_name = tempfile.mkstemp(dir=str(parent), prefix=".entry-", suffix=".png")
    # mkstemp defaults to 0600; the final artifact must be world-readable (0644)
    # so a distinct-uid reader can open it. The chmod deliberately runs inside
    # the try and the fdopen context, after write/flush/fsync and before the
    # file closes and os.replace runs: a chmod failure follows the existing
    # cleanup path, and the temp file is never world-readable while its bytes
    # are still being written.
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(fd, 0o644)
        os.replace(tmp_name, destination)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write the committed news-image PNG bytes to the output location."
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="destination PNG path (overrides MAKEFUN_OUTPUT_DIR and /output default)",
    )
    args = parser.parse_args(argv)

    destination = resolve_output_path(args.output)
    try:
        data = read_committed_png()
        write_output(data, destination)
    except OutputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: cannot write output: {exc}", file=sys.stderr)
        return 1

    print(f"wrote {destination} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

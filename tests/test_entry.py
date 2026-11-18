#!/usr/bin/env python3
"""Deterministic / integrity tests for the news image entry.

Standard library only. Run: python3 tests/test_entry.py
"""

from __future__ import annotations

import hashlib
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MAIN = REPO / "main.py"
ENTRY = REPO / "entry.png"
DESIGN = REPO / "design.html"

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_chunks(data: bytes):
    assert data.startswith(PNG_SIGNATURE), "bad PNG signature"
    offset = 8
    chunks = []
    while offset < len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        ctype = data[offset + 4 : offset + 8]
        body = data[offset + 8 : offset + 8 + length]
        (crc,) = struct.unpack(">I", data[offset + 8 + length : offset + 12 + length])
        assert zlib.crc32(ctype + body) & 0xFFFFFFFF == crc, f"CRC fail {ctype}"
        chunks.append((ctype, body))
        offset += 12 + length
    assert chunks[-1][0] == b"IEND", "missing IEND"
    return chunks


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_main(*args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.pop("MAKEFUN_OUTPUT_DIR", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(MAIN), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=50,
    )


def chunk(ctype: bytes, body: bytes) -> bytes:
    """Serialize one PNG chunk: length, type, body, CRC32(type+body)."""
    return struct.pack(">I", len(body)) + ctype + body + struct.pack(
        ">I", zlib.crc32(ctype + body) & 0xFFFFFFFF
    )


def ihdr_body(width: int = 1024, height: int = 960) -> bytes:
    return struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)


def make_png(*chunks: bytes) -> bytes:
    """Build a synthetic PNG byte stream from pre-serialized chunks."""
    return PNG_SIGNATURE + b"".join(chunks)


class TestChunkOrder(unittest.TestCase):
    """Guards for the mandatory PNG chunk order enforced by verify_png."""

    def setUp(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("main_mod_order", MAIN)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.verify = mod.verify_png

    def test_valid_minimal_png_passes(self):
        png = make_png(chunk(b"IHDR", ihdr_body()), chunk(b"IDAT", b"\x00"), chunk(b"IEND", b""))
        self.assertIsNone(self.verify(png))

    def test_ihdr_must_be_first_chunk(self):
        png = make_png(chunk(b"IDAT", b"\x00"), chunk(b"IHDR", ihdr_body()), chunk(b"IEND", b""))
        with self.assertRaisesRegex(Exception, "first chunk"):
            self.verify(png)

    def test_duplicate_ihdr_rejected(self):
        png = make_png(
            chunk(b"IHDR", ihdr_body()), chunk(b"IHDR", ihdr_body()),
            chunk(b"IDAT", b"\x00"), chunk(b"IEND", b""),
        )
        with self.assertRaisesRegex(Exception, "duplicate IHDR"):
            self.verify(png)

    def test_at_least_one_idat_required(self):
        png = make_png(chunk(b"IHDR", ihdr_body()), chunk(b"IEND", b""))
        with self.assertRaisesRegex(Exception, "missing IDAT"):
            self.verify(png)

    def test_no_chunks_may_follow_iend(self):
        png = make_png(
            chunk(b"IHDR", ihdr_body()), chunk(b"IDAT", b"\x00"),
            chunk(b"IEND", b""), chunk(b"IDAT", b"\x00"),
        )
        with self.assertRaisesRegex(Exception, "follow IEND"):
            self.verify(png)

    def test_second_iend_rejected(self):
        png = make_png(
            chunk(b"IHDR", ihdr_body()), chunk(b"IDAT", b"\x00"),
            chunk(b"IEND", b""), chunk(b"IEND", b""),
        )
        with self.assertRaisesRegex(Exception, "follow IEND"):
            self.verify(png)

    def test_missing_iend_rejected(self):
        png = make_png(chunk(b"IHDR", ihdr_body()), chunk(b"IDAT", b"\x00"))
        with self.assertRaisesRegex(Exception, "missing IEND"):
            self.verify(png)

    def test_committed_entry_png_satisfies_order(self):
        self.assertIsNone(self.verify(ENTRY.read_bytes()))


class TestRuntime(unittest.TestCase):
    def test_explicit_output_writes_exact_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "entry.png"
            proc = run_main("--output", str(out))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            committed = ENTRY.read_bytes()
            self.assertEqual(out.read_bytes(), committed)
            self.assertIn(f"wrote {out}", proc.stdout)

    def test_makefun_output_dir_env_honored(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = run_main(env_extra={"MAKEFUN_OUTPUT_DIR": tmp})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = Path(tmp) / "entry.png"
            self.assertTrue(out.is_file())
            self.assertEqual(out.read_bytes(), ENTRY.read_bytes())

    def test_default_path_resolution(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("main_mod", MAIN)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["MAKEFUN_OUTPUT_DIR"] = tmp
            try:
                self.assertEqual(mod.resolve_output_path(None), Path(tmp) / "entry.png")
            finally:
                del os.environ["MAKEFUN_OUTPUT_DIR"]
            self.assertEqual(mod.resolve_output_path("/x/y.png"), Path("/x/y.png"))
            self.assertEqual(mod.resolve_output_path(None), Path("/output/entry.png"))

    def test_determinism_two_runs_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a.png"
            b = Path(tmp) / "b.png"
            self.assertEqual(run_main("--output", str(a)).returncode, 0)
            self.assertEqual(run_main("--output", str(b)).returncode, 0)
            self.assertEqual(sha256(a.read_bytes()), sha256(b.read_bytes()))

    def test_stdlib_only_imports(self):
        source = MAIN.read_text()
        allowed = {"argparse", "os", "pathlib", "struct", "sys", "tempfile", "zlib", "__future__"}
        for line in source.splitlines():
            line = line.strip()
            if line.startswith("import "):
                mod = line.split()[1].split(".")[0].rstrip(",")
                self.assertIn(mod, allowed, f"non-stdlib or unexpected import: {mod}")
            elif line.startswith("from ") and " import " in line:
                mod = line.split()[1].split(".")[0]
                self.assertIn(mod, allowed, f"non-stdlib or unexpected import: {mod}")

    def test_rejects_corrupt_png(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("main_mod", MAIN)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        good = ENTRY.read_bytes()
        bad = bytearray(good)
        bad[41] ^= 0xFF  # flip a byte inside IHDR
        with self.assertRaises(Exception):
            mod.verify_png(bytes(bad))


class TestImage(unittest.TestCase):
    def setUp(self):
        self.data = ENTRY.read_bytes()
        self.chunks = png_chunks(self.data)

    def test_size_under_1mib(self):
        self.assertLessEqual(len(self.data), 1024 * 1024)

    def test_dimensions_1024x960(self):
        ihdr = dict(self.chunks)[b"IHDR"]
        width, height = struct.unpack(">II", ihdr[0:8])
        self.assertEqual((width, height), (1024, 960))
        self.assertLessEqual(width, 1024)
        self.assertLessEqual(height, 1024)

    def test_pixel_stream_decodes(self):
        """zlib-decompress the IDAT stream; check scanline size is exact."""
        ihdr = dict(self.chunks)[b"IHDR"]
        width, height, bitdepth, colortype = struct.unpack(">IIBB", ihdr[0:10])
        self.assertEqual(bitdepth, 8)
        self.assertIn(colortype, (2, 6))  # RGB or RGBA
        channels = 3 if colortype == 2 else 4
        raw = zlib.decompress(b"".join(b for t, b in self.chunks if t == b"IDAT"))
        self.assertEqual(len(raw), height * (1 + width * channels))

    def test_no_trailing_junk(self):
        self.assertEqual(len(self.chunks[-1][1]), 0)  # IEND empty


class TestDesignContent(unittest.TestCase):
    """The composed visual must carry the required editorial copy."""

    def setUp(self):
        self.html = DESIGN.read_text()

    def check(self, *needles: str):
        for needle in needles:
            self.assertIn(needle, self.html)

    def test_masthead(self):
        self.check("WORLD BRIEF", "DAILY SIGNALS", "WEDNESDAY · 18 NOVEMBER 2026")

    def test_hero(self):
        self.check(
            "THE DAY, IN THREE MOVEMENTS",
            "A crowded<br>world stage.",
            "APEC leaders converge, climate voices continue in Antalya, and a security march draws thousands in Haiti.",
            "THREE SIGNALS FROM THE WORLD",
            "SUMMITS · CLIMATE · PUBLIC SAFETY",
        )

    def test_card1(self):
        self.check(
            "APEC · SHENZHEN", "18–19 NOV", "Summit in the making",
            "scheduled for Thursday, 19 Nov.", "18 NOV", "APEC leaders gather",
            "19 NOV", "Trilateral meeting due", "TRILATERAL MEETING · 19 NOV",
        )
        self.assertNotIn("has met", self.html)  # must not imply the meeting already happened

    def test_card2(self):
        self.check(
            "COP31 · ANTALYA", "17–18 NOV", "Climate voices continue",
            "continue through 18 Nov.", "High-level statements", "Statements continue",
            "LEADERS’ STATEMENTS · 17–18 NOV",
        )

    def test_card3(self):
        self.check(
            "HAITI · PORT-AU-PRINCE", "REPORTED 18 NOV", "Thousands march for security",
            "The march was held on 17 Nov.", "PROTEST HELD TUE · 17 NOV",
        )

    def test_stat_strip(self):
        self.check(
            "HAITI · UN FIGURES CITED BY AFP", "Armed violence<br>Jan–Oct 2026",
            "4,595", "KILLED", "2,050", "INJURED", "2,000+",
            "Salvadoran personnel deployed since late October, per AFP.",
        )

    def test_footer(self):
        self.check(
            "WORLD", "18 NOV 2026 · A daily news picture",
            "Le Monde · UNFCCC · AFP / UN figures",
            "Full source links and date notes in README",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

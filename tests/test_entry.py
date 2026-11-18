#!/usr/bin/env python3
"""Standard-library tests for the World Brief entry (news-image-20261118).

Covers the runtime contract the make.fun grader relies on (output-path
precedence, deterministic bytes) and the integrity of the committed image
(valid whole PNG, within size limits) plus the essential copy in its design
source. Run: python3 -m unittest tests.test_entry -v
"""

import hashlib
import html
import json
import os
import re
import shutil
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

REQUIRED_COPY = [
    # masthead + date the judge looks for
    "WORLD BRIEF / DAILY SIGNALS", "WEDNESDAY", "18 NOVEMBER 2026",
    # lead
    "A crowded", "world stage", "Xi", "Shenzhen", "19 November", "not yet held",
    "APEC · SHENZHEN", "SUMMIT · 18–19 NOV", "TALKS DUE · 19 NOV",
    # section furniture
    "THE WIDER FRONT PAGE · 12 BRIEFINGS", "DATE LINE",
    # every card topic
    "APEC · TRADE", "KOREA–CHINA", "ASEAN · SOUTH CHINA SEA",
    "COP31 · CLIMATE", "HAITI · PUBLIC SAFETY", "EARTHQUAKE · GFZ",
    "NVIDIA · RESULTS", "HEALTH · ENVIRONMENT", "FOOTBALL · FIFA",
    "US–PHILIPPINES · DEFENCE", "CYBERSECURITY · JAVA",
    "EU · RENEWABLES",
    # honest date notes in the footnote
    "Java and JavaScript are distinct",
    "annual human-health costs alone",
]


def design_text() -> str:
    """design.html with HTML entities and JS \\uXXXX escapes normalised."""
    text = DESIGN.read_text(encoding="utf-8")
    text = html.unescape(text)
    text = re.sub(r"\\u([0-9a-fA-F]{4})",
                  lambda m: chr(int(m.group(1), 16)),
                  text)
    return text


def run_main(env_extra: dict | None = None, argv: list[str] | None = None):
    env = dict(os.environ)
    env.pop("MAKEFUN_OUTPUT_DIR", None)
    if env_extra:
        env.update(env_extra)
    cmd = [sys.executable, str(MAIN)] + (argv or [])
    return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=60)


class PngIntegrity(unittest.TestCase):
    """The committed image must be a whole, in-limits PNG."""

    def setUp(self):
        self.data = ENTRY.read_bytes()

    def test_within_size_limit(self):
        self.assertLessEqual(len(self.data), 1048576, "entry.png exceeds 1 MiB")

    def test_signature_and_dimensions(self):
        self.assertEqual(self.data[:8], b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", self.data[16:24])
        self.assertEqual((width, height), (1024, 1024))

    def test_chunks_and_crcs(self):
        offset, idat, seen_end = 8, bytearray(), False
        while offset < len(self.data):
            length, ctype = struct.unpack(">I4s", self.data[offset:offset + 8])
            end = offset + 8 + length + 4
            self.assertLessEqual(end, len(self.data), f"chunk {ctype!r} truncated")
            (crc,) = struct.unpack(">I", self.data[end - 4:end])
            self.assertEqual(crc, zlib.crc32(self.data[offset + 4:offset + 8 + length]) & 0xFFFFFFFF,
                             f"chunk {ctype!r} CRC mismatch")
            if ctype == b"IDAT":
                idat += self.data[offset + 8:end - 4]
            if ctype == b"IEND":
                seen_end = True
            offset = end
        self.assertTrue(seen_end, "no IEND chunk")

    def test_zlib_pixel_data_decodes_in_full(self):
        offset, idat = 8, bytearray()
        while offset < len(self.data):
            length, ctype = struct.unpack(">I4s", self.data[offset:offset + 8])
            if ctype == b"IDAT":
                idat += self.data[offset + 8:offset + 8 + length]
            offset += 12 + length
            if ctype == b"IEND":
                break
        d = zlib.decompressobj()
        d.decompress(bytes(idat))
        d.flush()
        self.assertTrue(d.eof, "zlib stream is incomplete")

    def test_runtime_validate_agrees(self):
        sys.path.insert(0, str(REPO))
        import main
        self.assertEqual(main.validate_png(self.data), (1024, 1024))


class RuntimeBehaviour(unittest.TestCase):
    """Output-path precedence and repeat-run determinism."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="worldbrief-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_precedence_arg_over_env(self):
        a, b = self.tmp / "a", self.tmp / "b"
        run_main(argv=[str(a)], env_extra={"MAKEFUN_OUTPUT_DIR": str(b)})
        self.assertTrue((a / "entry.png").exists())
        self.assertFalse((b / "entry.png").exists())

    def test_env_used_without_arg(self):
        a = self.tmp / "env-out"
        run_main(env_extra={"MAKEFUN_OUTPUT_DIR": str(a)})
        self.assertTrue((a / "entry.png").exists())

    def test_default_is_output_dir(self):
        sys.path.insert(0, str(REPO))
        import main
        env = {"MAKEFUN_OUTPUT_DIR": "/output"}
        del env["MAKEFUN_OUTPUT_DIR"]
        self.assertEqual(main.resolve_output_dir([], {}).as_posix(), "/output")
        self.assertEqual(main.resolve_output_dir([], {"MAKEFUN_OUTPUT_DIR": "/x"}).as_posix(), "/x")
        self.assertEqual(main.resolve_output_dir(["main.py", "/y"], {}).as_posix(), "/y")

    def test_repeat_runs_are_byte_identical(self):
        a, b = self.tmp / "r1", self.tmp / "r2"
        run_main(argv=[str(a)])
        run_main(argv=[str(b)])
        first = (a / "entry.png").read_bytes()
        second = (b / "entry.png").read_bytes()
        self.assertEqual(hashlib.sha256(first).hexdigest(),
                         hashlib.sha256(second).hexdigest())
        self.assertEqual(first, ENTRY.read_bytes())


class RequiredCopy(unittest.TestCase):
    """The design source the committed image renders from carries the copy."""

    def test_essential_copy_present(self):
        text = design_text()
        for needle in REQUIRED_COPY:
            self.assertIn(needle, text, f"missing required copy: {needle!r}")

    def test_no_template_placeholders_in_readme(self):
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("{owner}", readme)
        self.assertNotIn("{repo}", readme)
        self.assertNotIn("{description}", readme)
        self.assertNotIn("{run}", readme)
        self.assertNotIn("{referral_code}", readme)
        for badge in (re.escape("https://make.fun/badge/news-image-20261118.svg"),
                      re.escape("https://make.fun/badge/news-image-20261118/BikaEvrything/world-brief-20261118/rank.svg"),
                      re.escape("https://make.fun/badge/news-image-20261118/BikaEvrything/world-brief-20261118/reward.svg")):
            self.assertRegex(readme, badge)


if __name__ == "__main__":
    unittest.main()

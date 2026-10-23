#!/usr/bin/env python3
"""Rejects invisible and bidirectional control characters in the repository's text files.

They make code display differently from how it runs ("Trojan Source", CVE-2021-42574):
a reviewer reads one thing, the interpreter executes another. Write them as escapes
instead (e.g. "\\u202e" in a string). The zero-width joiner (U+200D) is allowed — it is
part of ordinary emoji sequences.

Usage: python3 .github/scripts/check_unicode.py   (from the repo root)
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# built from code points, so this file contains none of the characters it forbids
_FORBIDDEN_CODEPOINTS = [
    *range(0x202A, 0x202F),  # LRE, RLE, PDF, LRO, RLO
    *range(0x2066, 0x206A),  # LRI, RLI, FSI, PDI
    0x200B,
    0x200C,
    0x200E,
    0x200F,  # zero-width space/non-joiner, LRM, RLM
    0x2028,
    0x2029,
    0xFEFF,  # line/paragraph separator, BOM / zero-width no-break space
]
FORBIDDEN = re.compile("[" + "".join(map(chr, _FORBIDDEN_CODEPOINTS)) + "]")
BINARY_SUFFIXES = (".png", ".ico", ".jpg", ".gz", ".zip")


def problems_in(text: str, name: str) -> list[str]:
    found = []
    # split on \n only: str.splitlines() also splits on U+2028/U+2029 and would hide them
    for no, line in enumerate(text.split("\n"), 1):
        for m in FORBIDDEN.finditer(line):
            found.append(f"{name}:{no}:{m.start() + 1}: U+{ord(m.group()):04X}")
    return found


def tracked_files() -> list[str]:
    git = shutil.which("git")
    if git is None:
        raise SystemExit("git is not installed")
    out = subprocess.run(  # noqa: S603 — path from shutil.which, constant arguments
        [git, "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT, capture_output=True, check=True
    ).stdout
    return [f for f in out.decode("utf-8", errors="surrogateescape").split("\0") if f]


def main() -> int:
    found = []
    for name in tracked_files():
        path = ROOT / name
        if name.endswith(BINARY_SUFFIXES) or not path.is_file():
            continue
        found += problems_in(path.read_text(encoding="utf-8", errors="replace"), name)
    if found:
        print("::error::Invisible/bidirectional control characters found (write them as escapes):")
        for f in found:
            print(f"::error::{f}")
        return 1
    print("Unicode check OK: no invisible or bidirectional control characters.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

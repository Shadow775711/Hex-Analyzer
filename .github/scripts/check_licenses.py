#!/usr/bin/env python3
"""Copyright and license check (run in CI).

1. Licenses of backend (pip-licenses) and frontend (package-lock.json) dependencies
   must be compatible with the project license (MIT) — no GPL/AGPL/LGPL etc.
2. Our files must not contain foreign copyright/license headers
   (a typical trace of code pasted from another project).

It cannot detect copied code without any notice — the author of the change is
responsible for that (see CONTRIBUTING.md, AGENTS.md).

Usage: python3 .github/scripts/check_licenses.py   (from the repo root, in an
environment with backend/requirements-dev.txt installed)
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Permissive licenses — compatible with MIT, allowed in the application
ALLOWED = {
    "MIT",
    "MIT-0",
    "ISC",
    "0BSD",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "Apache-2.0",
    "PSF-2.0",
    "Zlib",
    "CC0-1.0",
    "Unlicense",
    "BlueOak-1.0.0",
    "MPL-2.0",  # file-level copyleft: using the library unmodified is fine
}
# Development tools only (not shipped in the built application)
ALLOWED_DEV_ONLY = {"CC-BY-4.0"}  # e.g. caniuse-lite data used at build time

# Python metadata spelling → SPDX identifier
ALIASES = {
    "MIT License": "MIT",
    # "BSD License" (classifier) is ambiguous — could be BSD-4-Clause, so it is not aliased
    "Apache Software License": "Apache-2.0",
    "Apache License 2.0": "Apache-2.0",
    "Python Software Foundation License": "PSF-2.0",
    "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "ISC License (ISCL)": "ISC",
}

# Deliberate exceptions: {"package-name": "justification"} — added by a human, with a reason
EXCEPTIONS: dict[str, str] = {}

FOREIGN_HEADER = re.compile(
    r"copyright\s*(\(c\)|©|\d{4})|\(c\)\s*\d{4}|©\s*\d{4}|SPDX-License-Identifier|all rights reserved|"
    r"licensed under the|GNU (Lesser |Affero )?General Public License|\b(A|L)?GPL-?v?[23]\b|"
    r"free software; you can redistribute",
    re.IGNORECASE,
)
# files that legitimately contain example headers (this script and its tests)
HEADER_SCAN_SKIP = {"LICENSE", ".github/scripts/check_licenses.py", ".github/scripts/test_check_licenses.py"}


def license_ok(expr: str, dev: bool) -> bool:
    """SPDX-like expression: 'A OR B' needs one allowed side, 'A AND B' (and Python's
    'A; B' classifier lists) need all; parentheses group; 'X WITH exception' counts as X.
    Anything we cannot parse fails closed."""
    allowed = ALLOWED | (ALLOWED_DEV_ONLY if dev else set())
    expr = (expr or "").strip()
    if not expr or expr.upper() in {"UNKNOWN", "MISSING"}:
        return False
    if ALIASES.get(expr, expr) in allowed:
        return True
    if ";" in expr:
        return all(license_ok(part, dev) for part in expr.split(";"))
    try:
        tokens = re.findall(r"\(|\)|[^\s()]+", expr)
        value, rest = _or(tokens, allowed)
        return value and not rest
    except (IndexError, ValueError):
        return False


def _or(tokens: list[str], allowed: set[str]) -> tuple[bool, list[str]]:
    value, tokens = _and(tokens, allowed)
    while tokens and tokens[0].upper() == "OR":
        right, tokens = _and(tokens[1:], allowed)
        value = value or right
    return value, tokens


def _and(tokens: list[str], allowed: set[str]) -> tuple[bool, list[str]]:
    value, tokens = _atom(tokens, allowed)
    while tokens and tokens[0].upper() == "AND":
        right, tokens = _atom(tokens[1:], allowed)
        value = value and right
    return value, tokens


def _atom(tokens: list[str], allowed: set[str]) -> tuple[bool, list[str]]:
    if tokens[0] == "(":
        value, tokens = _or(tokens[1:], allowed)
        if not tokens or tokens[0] != ")":
            raise ValueError("unbalanced parentheses")
        return value, tokens[1:]
    if tokens[0] in {")", "AND", "OR", "WITH"} or tokens[0].upper() in {"AND", "OR", "WITH"}:
        raise ValueError(f"unexpected {tokens[0]}")
    name, tokens = tokens[0], tokens[1:]
    if tokens and tokens[0].upper() == "WITH":  # e.g. "GPL-2.0 WITH Classpath-exception-2.0"
        tokens = tokens[2:]
    return name in allowed, tokens


def python_deps() -> list[tuple[str, str, bool]]:
    out = subprocess.run(
        # same interpreter as this script → licenses of exactly this environment
        [sys.executable, "-m", "piplicenses", "--from=mixed", "--format=json", "--with-system"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [(p["Name"], p["License"], False) for p in json.loads(out)]


def npm_deps(lock: Path) -> list[tuple[str, str, bool]]:
    packages = json.loads(lock.read_text())["packages"]
    return [
        (path.split("node_modules/")[-1], meta.get("license", "MISSING"), bool(meta.get("dev")))
        for path, meta in packages.items()
        if path  # "" is the project itself
    ]


def foreign_headers() -> list[str]:
    git = shutil.which("git")
    if git is None:
        raise SystemExit("git is not installed")
    # -z: NUL-separated, so names with spaces or non-ASCII characters are not split or C-quoted;
    # --others: new, not yet committed files are scanned too (catches problems before the commit)
    out = subprocess.run(  # noqa: S603 — path from shutil.which, constant arguments
        [git, "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT, capture_output=True, check=True
    ).stdout
    files = [f for f in out.decode("utf-8", errors="surrogateescape").split("\0") if f]
    hits = []
    for name in files:
        if name in HEADER_SCAN_SKIP or name.endswith(("package-lock.json", ".png", ".ico")):
            continue
        path = ROOT / name
        if not path.is_file():  # tracked but deleted in the working tree — nothing to scan
            continue
        text = path.read_text(encoding="utf-8", errors="replace")  # non-UTF-8 files are scanned too
        for no, line in enumerate(text.splitlines(), 1):
            if FOREIGN_HEADER.search(line):
                hits.append(f"{name}:{no}: {line.strip()[:100]}")
    return hits


def main() -> int:
    problems = []
    deps = python_deps() + npm_deps(ROOT / "frontend" / "package-lock.json")
    for name, lic, dev in deps:
        if name not in EXCEPTIONS and not license_ok(lic, dev):
            problems.append(
                f'dependency {name}{" (dev)" if dev else ""}: license "{lic}" — incompatible with MIT or unknown'
            )
    for hit in foreign_headers():
        problems.append(f"foreign copyright/license header: {hit}")

    if problems:
        print("::error::License check failed:")
        for p in sorted(set(problems)):
            print(f"::error::{p}")
        print(
            "Remove/replace the dependency or the code. Deliberate exception: add it to EXCEPTIONS with a justification."
        )
        return 1
    print(f"Licenses OK: {len(deps)} dependencies checked, no foreign headers in the code.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

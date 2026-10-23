"""Tests for check_licenses.py — the license expression parser and the header regex."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("check_licenses", Path(__file__).parent / "check_licenses.py")
lic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lic)


@pytest.mark.parametrize(
    ("expr", "dev", "ok"),
    [
        ("MIT", False, True),
        ("MIT License", False, True),
        ("Apache Software License; MIT License", False, True),
        ("Apache-2.0 OR BSD-2-Clause", False, True),
        ("(MIT OR GPL-3.0-only)", False, True),
        ("MIT OR (GPL-3.0-only AND AGPL-3.0-only)", False, True),  # OR = choice
        ("BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0", False, True),
        ("Apache-2.0 WITH LLVM-exception", False, True),
        ("CC-BY-4.0", True, True),
        # must be rejected
        ("(MIT OR Apache-2.0) AND GPL-3.0-only", False, False),  # audit bypass
        ("GPL-3.0", False, False),
        ("GPL-3.0-or-later", True, False),
        ("AGPL-3.0", False, False),
        ("LGPL-2.1", False, False),
        ("MIT AND GPL-2.0", False, False),
        ("GPL-2.0 WITH Classpath-exception-2.0", False, False),
        ("CC-BY-4.0", False, False),
        ("BSD License", False, False),  # ambiguous classifier
        ("UNKNOWN", False, False),
        ("", False, False),
        ("(MIT", False, False),
        ("MIT OR", False, False),
        ("Proprietary", False, False),
    ],
)
def test_license_ok(expr, dev, ok):
    assert lic.license_ok(expr, dev) is ok


@pytest.mark.parametrize(
    "line",
    [
        "# Copyright (c) 2019 Jan Kowalski",
        "// Copyright 2021 Google LLC",
        "/* (C) 2020 Some Corp */",
        "/* SPDX-License-Identifier: GPL-2.0 */",
        "# Licensed under the Apache License, Version 2.0",
        "This program is free software; you can redistribute it and/or modify",
        "Released under GPLv3",
        "All rights reserved.",
    ],
)
def test_foreign_header_detected(line):
    assert lic.FOREIGN_HEADER.search(line)


@pytest.mark.parametrize("line", ["licenses compatible with MIT (no GPL/AGPL/LGPL)", "copy the file", "copyright-free"])
def test_plain_text_not_flagged(line):
    assert not lic.FOREIGN_HEADER.search(line)

"""Tests for check_unicode.py."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("check_unicode", Path(__file__).parent / "check_unicode.py")
uni = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uni)


@pytest.mark.parametrize("code", [0x202E, 0x2066, 0x2069, 0x200B, 0x200F, 0xFEFF, 0x2028])
def test_forbidden_characters_reported(code):
    found = uni.problems_in(f'access = "user{chr(code)}" # admin', "x.py")
    assert found == [f"x.py:1:15: U+{code:04X}"]


def test_escapes_emoji_and_diacritics_are_fine():
    text = 'name = "photo\\u202e.exe"  # 👨‍💻 zdjęcie'
    assert uni.problems_in(text, "x.py") == []

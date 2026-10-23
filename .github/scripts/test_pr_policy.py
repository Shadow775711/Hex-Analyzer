"""Tests for pr_policy.py — including the bypasses found in the security audit."""

import importlib.util
from pathlib import Path

import pytest

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location("pr_policy", HERE / "pr_policy.py")
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)

TEMPLATE = (HERE.parent / "pull_request_template.md").read_text()
AI_LINE = '- [ ] With AI help — briefly describe what for (e.g. "test draft", "regex hint"):'


def body(no_ai=False, ai=None, declaration=False, base=TEMPLATE):
    b = base
    if no_ai:
        b = b.replace("- [ ] No AI", "- [x] No AI")
    if ai is not None:
        b = b.replace(AI_LINE, AI_LINE.replace("[ ]", "[x]") + ai)
    if declaration:
        b = b.replace("- [ ] I understand", "- [X] I understand")
    return b


def errors(text, login="jan", kind="User"):
    return policy.check({"pull_request": {"user": {"login": login, "type": kind}, "body": text}})


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        (body(no_ai=True, declaration=True), True),
        (body(ai=" test draft for graph.py", declaration=True), True),
        (body(ai="\nhelped write the ELF validator", declaration=True), True),
        (TEMPLATE, False),
        (body(ai="", declaration=True), False),  # no description
        (body(no_ai=True, ai=" something", declaration=True), False),  # both options
        (body(declaration=True), False),  # no AI option
        (body(no_ai=True), False),  # no declaration
        (None, False),
    ],
)
def test_template_cases(text, ok):
    assert (errors(text) == []) is ok


def test_bot_rejected_dependabot_allowed():
    assert errors(body(no_ai=True, declaration=True), login="Copilot", kind="Bot")
    assert errors("anything", login="dependabot[bot]", kind="Bot") == []


# --- bypasses from the audit -------------------------------------------------


def test_edited_template_line_needs_real_description():
    b = body(declaration=True).replace(AI_LINE, "- [x] With AI help — x")
    assert errors(b)
    b = body(declaration=True).replace(AI_LINE, "- [x] With AI help")
    assert errors(b)


def test_next_checkbox_is_not_a_description():
    b = body(ai="", declaration=True)
    assert "- [ ] CI is green" in b
    assert errors(b)


def test_star_bullet_counts_as_second_option():
    b = body(no_ai=True, declaration=True) + "\n* [x] With AI help — wrote everything\n"
    assert errors(b)


def test_ticks_inside_unclosed_comment_do_not_count():
    # an unclosed comment at the end hides everything after it from the reviewer
    hidden = TEMPLATE + "\n<!--\n- [x] No AI\n- [x] I understand every change in this PR\n"
    assert errors(hidden)
    # a comment opened earlier is closed by the template's first "-->", so the rest IS visible
    visible = "<!-- note\n" + body(no_ai=True, declaration=True)
    assert errors(visible) == []


def test_ticks_inside_code_fence_do_not_count():
    fenced = TEMPLATE + "\n```\n- [x] No AI\n- [x] I understand every change in this PR\n```\n"
    assert errors(fenced)


def test_injection_text_is_only_data(tmp_path):
    marker = tmp_path / "PWNED"
    text = f"$(touch {marker}) `touch {marker}` " + body(no_ai=True, declaration=True)
    assert errors(text) == []
    assert not marker.exists()

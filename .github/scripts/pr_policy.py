#!/usr/bin/env python3
"""PR policy: reject PRs opened by bot accounts (except Dependabot) and PRs without
a filled-in "AI usage" section and author declaration (see the PR template).

Input: the GitHub event file (argv[1] or $GITHUB_EVENT_PATH). The PR body is read from
that file — never interpolated into the workflow — so it cannot inject commands.

Usage: python3 .github/scripts/pr_policy.py "$GITHUB_EVENT_PATH"
"""

import json
import os
import re
import sys

DEPENDABOT = "dependabot[bot]"
TEMPLATE_HINT = 'briefly describe what for (e.g. "test draft", "regex hint"):'
MIN_DESCRIPTION = 5

CHECKBOX = re.compile(r"^\s*[-*+]\s*\[(?P<mark>[ xX])\]\s*(?P<text>.*)$")


def visible_markdown(body: str) -> str:
    """Body as the reviewer sees it: without HTML comments (also an unclosed one, which
    hides everything after it) and without fenced code blocks (ticks there are not ticks)."""
    body = re.sub(r"<!--.*?(-->|\Z)", "", body, flags=re.S)
    return re.sub(r"^\s*(```|~~~).*?(^\s*\1|\Z)", "", body, flags=re.S | re.M)


def ticked(lines: list[str], prefix: str) -> list[int]:
    """Indexes of ticked checkbox lines whose text starts with `prefix` (case-insensitive)."""
    hits = []
    for i, line in enumerate(lines):
        m = CHECKBOX.match(line)
        if m and m["mark"] in "xX" and m["text"].lower().startswith(prefix.lower()):
            hits.append(i)
    return hits


def ai_description(lines: list[str], i: int) -> str:
    """Text describing the AI use: after "With AI help" on the same line (minus the template
    hint and separators), or the next non-empty line that is not a heading or a checkbox."""
    text = CHECKBOX.match(lines[i])["text"][len("With AI help") :]
    text = text.replace(TEMPLATE_HINT, "")
    text = re.sub(r"^[\s—–:\-]+", "", text).strip()
    if text:
        return text
    for line in lines[i + 1 :]:
        if not line.strip():
            continue
        if line.lstrip().startswith("#") or CHECKBOX.match(line):
            return ""
        return line.strip()
    return ""


def check(event: dict) -> list[str]:
    pr = event.get("pull_request") or {}
    user = pr.get("user") or {}
    login, kind = user.get("login", ""), user.get("type", "")
    if login == DEPENDABOT:
        return []

    errors = []
    if kind == "Bot":
        errors.append(
            f"PR opened by a bot account ({login}). Autonomous PRs are not accepted — "
            "a human who takes responsibility for the change must submit it (see AGENTS.md)."
        )

    lines = visible_markdown(pr.get("body") or "").splitlines()
    no_ai, with_ai = ticked(lines, "No AI"), ticked(lines, "With AI help")
    if len(no_ai) + len(with_ai) != 1:
        errors.append('"AI usage" section: tick exactly one option ([x]).')
    elif with_ai and len(ai_description(lines, with_ai[0]).replace(" ", "")) < MIN_DESCRIPTION:
        errors.append('"AI usage" section: briefly describe what AI was used for.')

    if not ticked(lines, "I understand every change"):
        errors.append('Author declaration is not ticked: "I understand every change in this PR…".')
    return errors


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GITHUB_EVENT_PATH")
    if not path:
        print("::error::missing event file")
        return 2
    with open(path, encoding="utf-8") as f:
        event = json.load(f)
    errors = check(event)
    login = ((event.get("pull_request") or {}).get("user") or {}).get("login", "?")
    if not errors:
        print(f"PR policy met (author: {login}).")
        return 0
    for e in errors:
        print(f"::error::{e}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("### ❌ PR policy not met\n" + "".join(f"- {e}\n" for e in errors))
            f.write("\nFill in the PR description according to the template — the check re-runs when you edit it.\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())

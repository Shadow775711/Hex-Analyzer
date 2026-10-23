# AGENTS.md — rules for AI assistants

This file is read by AI assistants (Claude Code, GitHub Copilot, Cursor, Codex and others)
working in this repository.

## ⛔ Most important: you never send anything on your own

You may read code, propose changes and edit files when a human asks you to.
But **without an explicit request from the human in this conversation you MUST NOT**:

- run `git commit`,
- run `git push` (to any branch),
- open, approve or merge pull requests,
- open issues or write comments on GitHub,
- publish anything anywhere else.

Even when the human asks: **first show** exactly what will be sent
(list of files, changes, commit message) and **wait for their "yes"**.

A request covers that one thing only — the next commit is the next question.
A human is responsible for every change in this repository, so they decide what goes out and when.

## The human sends and talks

- Commits and pull requests should preferably be **sent by the human**, from their own account.
  Bot accounts and autonomous agents do not submit changes here — such PRs are rejected.
- In pull requests and issues **the human talks**, not the agent. Do not reply to reviewers
  or carry on discussions on their behalf.
- You may help the human **translate or phrase** a reply (e.g. when they don't speak the
  language of the discussion) — but they read it, understand it and post it as their own.
- The author of a commit is the human. Mark AI help with an `Assisted-by:` trailer
  (e.g. `Assisted-by: Claude:claude-opus-5-5`), **never** `Co-authored-by:` — an AI is a tool,
  not a co-author.

## A few facts about the project

- **Language:** code, comments, UI and documentation are in **English** — write the same way.
- **Check before saying "done"** — run it and show the human the result:
  ```bash
  cd backend  && ruff check . && ruff format --check . && pytest
  cd frontend && npm run lint && npm run format:check && npm test && npm run build
  ```
- **Explain your changes** to the human in plain words: what you changed and why.
- **No secrets in the repo**: passwords, tokens, keys, IP addresses, private files.
  `caddy/auth.caddy`, `caddy/password.txt` and `.env` are in `.gitignore` and must stay there.
- More about the project: [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md).

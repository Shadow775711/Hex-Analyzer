# Contributing to Hex Analyzer

Thanks for wanting to help! Every contribution counts: a bug report, a typo fix,
a new file signature, a test or a bigger feature.

## Before you start

- **Bugs and ideas** go to [Issues](../../issues) — there are templates.
- **Do NOT report security vulnerabilities publicly** — see [SECURITY.md](SECURITY.md).
- For a bigger change, open an issue first and describe the idea — it saves work on both sides.

## AI in this project

You may use AI (Copilot, Claude, ChatGPT, Cursor…) — it is a tool like any other.
But **a human is always responsible for the code** they submit:

- **You know what you want to achieve** before asking AI for code — and you can describe it in the PR.
- **You understand every line** you submit and can explain it in review.
  "That's what it generated" is not an answer.
- **You checked it yourself**: you ran the tests and the linters, and read the diff.
- **You say that you used AI** — the PR template has a place for it. It's not a minus, just
  information for the reviewer. In commits, add an `Assisted-by:` trailer
  (e.g. `Assisted-by: Claude:claude-opus-5-5`) — not `Co-authored-by:`: you are the author,
  AI is a tool.
- **You send and you talk.** You submit commits and PRs from your own account, and you reply
  in discussions, not a bot. Don't speak the language? Feel free to use AI to translate — as
  long as the reply is yours and you understand what you write.

What we **do not accept**:

- **PRs from autonomous agents and bot accounts** (except Dependabot) — the `pr-policy`
  workflow (`.github/scripts/pr_policy.py`) rejects them automatically, as well as PRs without a filled-in
  author declaration. It runs from the base branch (`pull_request_target`), so changes to it in your PR
  take effect only after merge;
- bulk, unchecked changes ("AI fixed 60 files"), invented APIs and packages,
  dead code and empty tests.

A maintainer may close a PR whose author cannot explain their change — without debating
how it was made. Rules for AI assistants themselves are in [AGENTS.md](AGENTS.md).

## Development environment

Requirements: Python 3.12+, Node.js 22+, (optionally) Docker.

```bash
# backend — http://localhost:8000 (API docs at /docs only with ENABLE_DOCS=1)
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt        # hashed lock, generated for Python 3.12
ENABLE_DOCS=1 uvicorn main:app --reload --port 8000

# frontend — http://localhost:5173 (Vite proxies /api to the backend)
cd frontend
npm ci
npm run dev
```

Checks before every commit (worth enabling once):

```bash
pip install pre-commit && pre-commit install
```

Hooks in `.pre-commit-config.yaml` are pinned to commit hashes; update them with
`pre-commit autoupdate --freeze` (never by hand to a bare tag).

## Changing dependencies

**Backend:** never edit `requirements.txt` / `requirements-dev.txt` by hand — they are locks with hashes,
and the Docker image installs them with `pip install --require-hashes`. Edit the top-level
`requirements.in` (or `requirements-dev.in`) and regenerate the lock with the command from its header,
inside Python 3.12 (the Docker image's Python), e.g.:

```bash
cd backend
docker run --rm -v "$PWD":/src -w /src -u "$(id -u):$(id -g)" -e HOME=/tmp python:3.12-slim sh -c '
  pip install --user --quiet pip-tools &&
  python -m piptools compile --generate-hashes --strip-extras --allow-unsafe -o requirements.txt requirements.in &&
  python -m piptools compile --generate-hashes --strip-extras --allow-unsafe -o requirements-dev.txt requirements-dev.in'
```

Commit the `.in` and the regenerated `.txt` together. The backend uses plain `uvicorn` (no `[standard]` extras).

**Frontend:** `npm install <pkg>@<version>` and commit `package-lock.json`. `package.json` has `overrides`
for patched transitive dependencies (`lodash-es`, `preact`) — keep them until the parent package ships
a fixed version.

## Tests and code style

CI runs the same checks on every pull request — a PR with red CI will not be merged.

| | Backend (`backend/`) | Frontend (`frontend/`) |
|---|---|---|
| Tests | `pytest` | `npm test` |
| Lint | `ruff check .` | `npm run lint` |
| Formatting | `ruff format .` | `npm run format` |

- **Licenses:** CI checks that dependencies have MIT-compatible licenses (no GPL/AGPL/LGPL)
  and that the code contains no foreign copyright headers (`.github/scripts/check_licenses.py`).
  In addition, SCANOSS compares the code with a database of open-source projects and blocks
  fragments under copyleft licenses (on PRs from forks it runs after merge). Do not paste code from other projects without checking
  its license — no automated tool is a guarantee, and you are responsible for it.
- **A new action in `.github/workflows/`** — only pinned to a full commit hash
  (`uses: owner/action@<sha> # vX.Y.Z`), never to a bare tag; `actions/checkout` with
  `persist-credentials: false`, and every job with `timeout-minutes`.
- **A new Docker base image** — pinned by version and digest (`image:tag@sha256:…`); Dependabot bumps it.
- **CI scripts** (`.github/scripts/`) have their own tests: `pytest .github/scripts` (run in the `licenses` job).
- **Security-sensitive behaviour** (limits, validation, error messages) is covered by
  `backend/tests/test_security.py` — extend it when you change such code.
- **New feature = new test.** Bug fix = a test that would have caught the bug.
- Backend tests use `TestClient` (no real server); background tasks run right after the
  response, so after `POST /upload` the result is already available.
- Every request that changes data (POST/DELETE) must send the `X-Hex-Analyzer` header
  (CSRF protection) — in tests the `client` fixture adds it.

## Conventions

- **Language:** code, comments, UI and documentation are in English.
- **Commits** follow [Conventional Commits](https://www.conventionalcommits.org/):
  `feat(backend): …`, `fix(frontend): …`, `docs: …`, `test: …`, `chore: …`.
- **One change = one PR.** A small PR gets reviewed faster.
- API change → update `docs/backend.md` and add an entry to `CHANGELOG.md` (*Unreleased* section).
- Change to the chunking algorithm or hit validation → bump `FEATURES_VERSION`
  in `backend/modules/features.py` (the backend will then recompute existing files).

## Adding a file signature

The easiest first contribution: add a format to `backend/modules/filetypes_seed.py`
(name, extension, magic HEX, offset, whether to search inside files), and if the signature
is 4 bytes long — add a header validator to `VALIDATORS` (`backend/modules/features.py`) and
a test in `backend/tests/test_features.py`. Details: [docs/signatures.md](docs/signatures.md).

## Pull request checklist

- [ ] "AI usage" section and author declaration filled in (required by CI)
- [ ] CI is green (tests, lint, formatting, build)
- [ ] tests for the new behaviour
- [ ] docs and `CHANGELOG.md` updated
- [ ] no secrets, passwords, IP addresses or private files in commits

By contributing, you agree to license your code under the [MIT](LICENSE) license
and to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

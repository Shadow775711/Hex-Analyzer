# Changelog

All notable changes to this project. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Upgrading from the previous version — read before `git pull`

1. **HTTPS and password.** The app now runs behind Caddy at `https://<host>` (port 443);
   the old port `8080` is closed. Before starting:
   ```bash
   cp .env.example .env          # enter your IP address
   ./caddy/set-password.sh       # login "admin" + a random password in caddy/password.txt
   ```
   Then import the Caddy CA into your browser — instructions in `caddy/README.md`.
2. **Non-root containers.** An existing data volume must be handed over to the backend user
   once:
   ```bash
   docker compose run --rm --no-deps --user root --entrypoint chown backend -R 10001:10001 /app/data
   ```
3. **New database.** Data goes to `data/hex.db` (the old `signatures.db` is not used).
   Jobs from before the upgrade are re-analyzed by the backend at startup, in the background.
4. **API clients** must send the `X-Hex-Analyzer` header (any value) on POST/DELETE, and a `Host`
   listed in `ALLOWED_HOSTS` (compose: `HEX_HOSTS` + `localhost`).
5. **New password hash.** Run `./caddy/set-password.sh` again — it creates a bcrypt cost-10 hash
   (cheaper failed logins, no login-flood DoS) together with a **new** random password in `caddy/password.txt`.
   `docker compose up` now fails if `caddy/auth.caddy` is missing.
6. **Listening address.** Set `HEX_BIND` in `.env` (see `.env.example`). The default is now `127.0.0.1`
   (this computer only) — for access from the LAN use the LAN IP (e.g. `192.168.1.50`) or `0.0.0.0`.
7. **Rebuild** with fresh, digest-pinned base images:
   ```bash
   docker compose build --pull
   docker compose up -d
   ```

### Added
- **Relations between files**: similar (content-defined chunks + Jaccard, robust to
  insertions), contains (signatures inside the file, with header verification), same name,
  same type, identical (one node with multiple names).
- `GET /jobs/{id}/graph` endpoint — graph computed live; a new graph in the UI with relation filters,
  a similarity threshold and a details panel ("Open this file").
- Signature database (~34 types, with offsets: TAR, MP4, ISO…) and its management:
  `GET`/`POST /types`, `DELETE /types/{id}`, `MAX_CUSTOM_TYPES` limit.
- File entropy and entropy profile (chart in the "File" tab, click → jump to HEX).
- "File" and "Relations" tabs; jump to offset in the HEX view.
- `DELETE /jobs/{id}` and optional cleanup of old jobs (`JOB_TTL_HOURS`).
- HTTPS via Caddy (`tls internal`), login (`caddy/set-password.sh`), security
  headers (CSP, HSTS, nosniff, X-Frame-Options).
- Tests: backend (pytest, including `test_security.py` for the hardening), frontend (Vitest + Testing Library),
  CI scripts (`pytest .github/scripts`).
- CI (GitHub Actions), Dependabot, pre-commit, `.editorconfig`, ruff, ESLint, Prettier.
- `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, issue and PR templates.
- Rules for using AI: `AGENTS.md` (the assistant never commits or sends anything on its own), a section in
  `CONTRIBUTING.md`, an author declaration in the PR template, a "PR policy" workflow rejecting
  PRs from bot accounts and PRs without the declaration, `CODEOWNERS`.
- Copyright checks in CI: dependency licenses (backend and frontend) compatible with MIT,
  no third-party copyright headers in the code; in PRs `dependency-review` (licenses
  and vulnerabilities of newly added dependencies).
- Scanners in CI ("Security" workflow): CodeQL (code), Trivy (Docker images, secrets),
  SCANOSS (copied code under copyleft licenses); weekly and on every PR.
- Backend settings `ALLOWED_HOSTS`, `ENABLE_DOCS`, `ANALYSIS_WORKERS`, `MAX_QUEUED_JOBS`, `MIN_FREE_MB`,
  `MAX_CUSTOM_SCAN_TYPES`; compose setting `HEX_BIND`.
- Graph file nodes carry `names_total`; the UI shows "+N more" for long name lists.
- Friendly upload error messages for `413`, `503` and `507`; an error boundary per tab.
- `robots.txt` with `Disallow: /`.

### Changed
- Backend: plain SQLAlchemy 2.0 instead of Flask-SQLAlchemy; single-pass analysis
  (numpy), without loading the whole file into memory; all data in `DATA_DIR`.
- Frontend: Vite instead of the abandoned Create React App; custom CSS instead of Mantine.
- Upload does not block the server; it responds `202 Accepted`.
- Dependencies pinned to tested versions.
- Backend and frontend containers run without root; the backend is not exposed to the outside.
- `POST /upload` can answer `503` (queue full) and `507` (disk almost full); an oversized `Content-Length`
  gets `413` before the body is read. Analysis runs in a dedicated executor, not the request thread pool.
- `GET /jobs/{id}`: `analysis_error` is always the generic "Analysis failed" (details in the server log).
- Graph file nodes: `names` sorted and capped at 20, plus `names_total`.
- `POST /types`: `409` for a duplicate `magic` + `offset` and above `MAX_CUSTOM_SCAN_TYPES` scanned types;
  `scan_inside` only for ≥ 4-byte signatures that are not one repeated byte; `extension` must match
  `[a-z0-9._-]{1,16}`. `/bytes` `offset` ≤ 2^62, `DELETE /types/{id}` `id` 1…2^31−1.
- `/docs`, `/redoc`, `/openapi.json` are off by default (`ENABLE_DOCS=1`).
- Startup maintenance sanitises signature rows and sweeps orphaned uploads/archives older than 1 h;
  promotion of seed rows to built-in is one-shot.
- Frontend: the graph is cached per job and refetched on Relations/Relation graph only when older than 10 s.
- Backend dependencies: `requirements.in` → `requirements.txt` lock with hashes (`pip-compile --generate-hashes`,
  Python 3.12), installed with `--require-hashes`; plain `uvicorn` instead of `uvicorn[standard]`.
- Caddy listens on `127.0.0.1` by default (`HEX_BIND`); upload limit `101MiB` (binary units); HSTS 1 day.
- `pr-policy` rewritten in Python (`.github/scripts/pr_policy.py`) and run via `pull_request_target`
  from the base branch; SCANOSS skipped on fork PRs (scanned after merge); job timeouts;
  Dependabot also for `docker-compose.yml`, with a 5-day cooldown; pre-commit hooks pinned by commit hash.
- Documentation, UI, code and comments translated to English; files renamed accordingly
  (e.g. `docs/frontend.md`, `docs/signatures.md`, `caddy/set-password.sh`).

### Removed
- `GET /signatures` (replaced by `/types`), `GET /` (`/ping` remains).
- Mantine, Emotion, Tabler Icons, axios, bootstrap, react-scripts, Flask.
- Text hex dump in the analysis result (the frontend renders it from the bytes).
- The built frontend (`frontend/build/`) from the repository.

### Fixed
- In Docker it was impossible to upload a file > 1 MB (missing `client_max_body_size` in nginx).
- `hexdump`/`hex_dump` typo — the analysis result contained hundreds of MB of text.
- Status polling did not stop on an analysis error.
- The database in Docker did not survive a container rebuild.
- Race condition: a `DELETE` during analysis left orphaned entries in the database.
- False "contains" hits in compressed data (e.g. a Java class in the kernel).
- Wrong UF2 signature.
- HEX context menu in the wrong place after scrolling the page.
- Bare magic bytes in front of a file (decoys) could push a real embedded file out of the 20-hits-per-type cap —
  hits are now validated before the cap.
- A custom type with a built-in extension could suppress built-in embedded hits — same-extension
  suppression now applies only between built-in types.
- `POST /types` stored magic with embedded whitespace (tabs, newlines) as-is; existing rows are cleaned up at startup.
- Very large `/bytes` offsets and type IDs caused `500` instead of `422`.
- Failed upload could leave an orphaned file behind.

### Security
- Similarity cost bounded: per file only a 2048-hash bottom-k sketch is stored (crafted files can no
  longer create hundreds of thousands of rows) and a graph request scores at most 200 candidates;
  `FEATURES_VERSION` 3 — existing files are recomputed on start.
- `POST /upload` without `Content-Length` → `411`; job directories left without their upload are swept;
  jobs interrupted by a restart are re-queued.
- Docker networks split (`edge`: Caddy ↔ frontend, `app`: frontend ↔ backend, internal).
- CI/pre-commit check against invisible and bidirectional control characters (Trojan Source).
- CSRF protection (`X-Hex-Analyzer` header), CORS disabled by default.
- DNS rebinding protection (Caddy answers only for hosts in `HEX_HOSTS`).
- Validation of `job_id` and file names (path traversal), signature limit (DoS).
- Backend `Host` validation (`ALLOWED_HOSTS`, `400` otherwise) as a second DNS-rebinding layer.
- Resource limits: bounded analysis queue, free-space floor, early `Content-Length` check, limit on
  custom scanned signatures; nginx streams uploads instead of buffering them.
- No error details in API responses; API docs disabled by default.
- Control/format characters (bidi overrides, zero-width…) stripped from file and signature names,
  file names capped at 150 UTF-8 bytes; the UI shows hidden characters as `⟨U+XXXX⟩`.
- force-graph's HTML tooltips disabled (`nodeLabel`/`linkLabel` empty — an `innerHTML` sink).
- Hardened containers: read-only root filesystem, `cap_drop: ALL` (Caddy: `NET_BIND_SERVICE` only),
  `no-new-privileges`, memory and pids limits; Caddy gets only `Caddyfile` + `auth.caddy`.
- Caddy: security headers also on error responses, Permissions-Policy, COOP, CORP, `img-src 'self'`,
  HSTS reduced to 1 day (private CA); `set-password.sh` passes the password via stdin, bcrypt cost 10.
- Images pinned by digest: `caddy:2.11.7`, `python:3.12.15-slim`, `node:22.23.4-alpine`,
  `nginx-unprivileged:1.31.7-alpine`; Python deps installed with `--require-hashes`.
- npm `overrides`: `lodash-es` 4.18.1 and `preact` 10.28.4 (security fixes).
- CI: `persist-credentials: false` on every checkout, PR policy from the base branch, Trivy also scans
  the Caddy image (report only), `dependency-review` allows `caniuse-lite`'s CC-BY-4.0 only for that package.
- GitHub Actions pinned to full commit hashes instead of tags (after the
  `trivy-action` compromise in March 2026 — tags can be moved, hashes cannot).
- Details and threat model: [SECURITY.md](SECURITY.md).

# Security

## Reporting a vulnerability

**Do not open a public issue** for a security vulnerability.

Report it privately through GitHub: the **Security → Report a vulnerability** tab
(*Private vulnerability reporting*). Please describe:

- what it affects (endpoint, file, version / commit),
- how to reproduce it (ideally a minimal example),
- what the possible impact is.

We aim to reply within 7 days and agree on a date for publishing the fix.
After the fix, the reporter is credited in `CHANGELOG.md` (unless they prefer otherwise).

## Supported versions

Security fixes go into the latest version on the `main` branch.

## Threat model — what the application assumes

Hex Analyzer is a tool for **a single user or a trusted group** on a local network.
Deliberate assumptions:

- **Every logged-in user has full access**: they see all files (the graph reveals the job IDs
  of other files), can delete them and add signatures. The application does not distinguish users —
  there is one shared login, so job IDs being visible to every logged-in user is by design, not a leak.
- **Login and HTTPS are provided by Caddy** (`caddy/`). Exposing the backend or the frontend
  bypassing Caddy means no authentication — don't do it. By default Caddy listens only on
  `127.0.0.1` (`HEX_BIND`); Docker publishes ports past the host firewall, so `0.0.0.0` really
  means every network the computer joins.
- **Do not expose the application to the internet** without an additional layer (VPN, a reverse
  proxy with strong authentication). Basic Auth protects against casual access on a home
  network, not against a determined attacker.
- **Analysed files are treated as hostile data**: the backend does not execute, unpack or parse
  them — it only reads bytes (header, hashes, patterns).

## Protections in the code

| Threat | Protection |
|---|---|
| SQL injection | ORM / parameterised queries only |
| XSS | React escapes data; no `innerHTML` (force-graph's HTML tooltips disabled: empty `nodeLabel`/`linkLabel`); CSP in Caddy (`script-src 'self'`, `img-src 'self'`) |
| Spoofed names | control/format characters (bidi overrides, zero-width…) stripped from file and signature names in the backend; the UI shows any left as `⟨U+XXXX⟩` (`displayName()`) |
| CSRF | changes (POST/DELETE) require the `X-Hex-Analyzer` header; CORS disabled by default |
| DNS rebinding | Caddy answers only for host names in `HEX_HOSTS`; the backend also checks `Host` against `ALLOWED_HOSTS` (`400` otherwise) |
| Path traversal | `job_id` validated by a pattern, file names reduced to the bare name (≤ 150 bytes of UTF-8) |
| Disk / RAM exhaustion | 100 MB per file (oversized `Content-Length` rejected before the body is read, uploads without `Content-Length` → `411`; Caddy `101MiB`), streaming reads, uploads streamed through nginx and spooled to the data volume, bounded queue (`MAX_QUEUED_JOBS` → `503`), free-space floor (`MIN_FREE_MB` → `507`), orphaned uploads and job directories swept, optional `JOB_TTL_HOURS` |
| Analysis slowdown | dedicated executor (`ANALYSIS_WORKERS`), similarity cost bounded (each file stores a 2048-hash bottom-k sketch; at most 200 candidates scored per graph request), interrupted jobs re-queued on start, limits on custom signatures (`MAX_CUSTOM_TYPES`, `MAX_CUSTOM_SCAN_TYPES`), duplicates rejected, inside-file search only for ≥ 4-byte non-repetitive signatures |
| Hidden embedded files | hits validated before the 20-per-type cap (decoys can't push real files out); a custom type cannot suppress built-in hits |
| Error disclosure | `analysis_error` is always "Analysis failed" (details only in the server log); `/docs`, `/redoc`, `/openapi.json` off unless `ENABLE_DOCS=1`; the frontend shows only short excerpts of error bodies |
| Login brute force / DoS | random ~130-bit password; bcrypt cost 10 so failed logins stay cheap; password passed to `caddy hash-password` via stdin |
| Network | separate Docker networks: Caddy ↔ frontend (`edge`) and frontend ↔ backend (`app`, internal — no internet access); Caddy cannot reach the backend directly |
| Hidden code (Trojan Source) | CI and pre-commit reject invisible/bidirectional control characters (`check_unicode.py`) |
| Privileges | non-root containers, read-only root filesystem, `cap_drop: ALL` (Caddy: only `NET_BIND_SERVICE`), `no-new-privileges`, memory and pids limits; Caddy gets only `Caddyfile` + `auth.caddy` (not `password.txt`) |
| Browser hardening | security headers also on error responses (`handle_errors`): CSP, HSTS (1 day — private CA), Permissions-Policy, COOP, CORP, `nosniff`, `X-Frame-Options`; `robots.txt` disallows everything |
| Supply chain | base images and Caddy pinned by digest; Python deps installed with `--require-hashes` from a `pip-compile` lock; npm `overrides` for patched `lodash-es` / `preact`; `npm ci --ignore-scripts`; Dependabot with a 5-day cooldown |

## Automated scanners (GitHub Actions)

| Tool | What it checks | Where to see results |
|---|---|---|
| **CodeQL** | vulnerabilities in Python and JS code (injection, XSS, path traversal…) | Security → Code scanning |
| **Trivy** | vulnerabilities in the backend and frontend images (blocking), the Caddy image (report only — fixed by a Caddy release), secrets leaked into the repo | `trivy` job log |
| **SCANOSS** | code copied from projects under copyleft licenses (GPL etc.); skipped on fork PRs (read-only token) — those are scanned after merge | comment on the PR |
| **Dependabot** + `dependency-review` | vulnerable / incompatibly licensed dependencies (pip, npm, Dockerfiles, `docker-compose.yml`, actions; 5-day cooldown); `caniuse-lite`'s CC-BY-4.0 is allowed for that package only | Security, PR |
| `check_licenses.py` | MIT-compatible dependency licenses, foreign copyright headers | `licenses` job log |
| `pr_policy.py` | PRs from bot accounts, missing author declaration — runs via `pull_request_target` from the **base** branch, so a PR cannot edit or disable it (the PR's code is never checked out) | `PR policy` check |

The CI scripts in `.github/scripts/` have their own tests (`pytest .github/scripts`, run in the `licenses` job).
All actions are pinned to a **full commit hash**, not a tag — a tag can be silently re-pointed
to malicious code (that is how `trivy-action` was hijacked in March 2026, CVE-2026-33634).
Every checkout uses `persist-credentials: false` and every job has a timeout. Pre-commit hooks are pinned
by commit hash too (`pre-commit autoupdate --freeze`).

Known limitations and ideas for further hardening are in `docs/backend.md` (TODO section).

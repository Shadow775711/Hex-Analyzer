# Hex Analyzer - Backend Documentation

## Table of contents
1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Installation and configuration](#installation-and-configuration)
4. [API Endpoints](#api-endpoints)
5. [Modules](#modules)
6. [Database](#database)
7. [File analysis workflow](#file-analysis-workflow)
8. [Security](#security)
9. [Tests and lint](#tests-and-lint)

---

## Overview

The **Hex Analyzer** backend is a **FastAPI** application that provides:
- Uploading binary files (up to 100 MB)
- Background analysis in a single pass: SHA-256, type (signature database), entropy with a profile,
  hashes of content-defined chunks, signatures hidden inside the file (verified)
- A relation graph between files: similar, contains, same name, same type, identical
- Signature database management (`GET`/`POST /types`, `DELETE /types/{id}`)
- Paged download of binary content (the hex dump is rendered by the frontend)
- File archiving in `.gz` format
- Deleting jobs manually (`DELETE`) or automatically after a while (TTL)

### Tech stack
- **Framework**: FastAPI (+ uvicorn)
- **Database**: SQLite (WAL) via SQLAlchemy 2.0
- **Computation**: numpy (byte histogram / entropy)
- **Versions**: top-level dependencies in `requirements.in`, locked with hashes in `requirements.txt`
  (`pip-compile --generate-hashes`, for the Python 3.12 of the Docker image); developer tools (pytest, ruff)
  in `requirements-dev.in` → `requirements-dev.txt`. Plain `uvicorn` (no `[standard]` extras)

---

## Architecture

```
backend/
├── main.py              # FastAPI app, endpoints, background analysis
├── models.py            # Tables + session factory (loads the initial signatures)
├── pyproject.toml       # pytest and ruff configuration
├── requirements.in      # Top-level app dependencies (edit this one)
├── requirements.txt     # Lock with hashes, generated from requirements.in
├── requirements-dev.in  # + pytest, ruff, pip-licenses
├── requirements-dev.txt # Lock with hashes, generated from requirements-dev.in
├── Dockerfile           # Image: digest-pinned base, user app (uid 10001), HEALTHCHECK
├── tests/               # pytest (test_api, test_graph, test_features, test_maintenance, test_security)
└── modules/
    ├── features.py      # File features in a single pass (pure functions)
    ├── analyzer.py      # Type from the signature database + storing the file in the database
    ├── graph.py         # Relation graph around a file
    └── filetypes_seed.py# Initial database of ~34 signatures
```

All data goes into a single `DATA_DIR` directory (`data/` by default):

```
data/
├── hex.db                      # SQLite database
├── uploads/<job_id>_<name>     # Original files
├── tmp/                        # Spooled multipart uploads (TMPDIR in Docker)
├── jobs/<job_id>/
│   ├── meta.json               # Job status (+ error, if any)
│   └── result.json             # Analysis result
└── archive/<job_id>/
    ├── input.bin.gz            # Compressed copy
    └── archive_meta.json
```

JSON files are written atomically (temporary file + `os.replace`), so
a poller never reads half a file.

---

## Installation and configuration

### Locally
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```
API: `http://localhost:8000`. The interactive docs (`/docs`, `/redoc`, `/openapi.json`) are **off by default** —
start with `ENABLE_DOCS=1 uvicorn main:app --reload --port 8000` to get them. The lock files are generated for
Python 3.12; on another Python version `pip` may not find a hashed wheel for every package.

### Docker
```bash
docker compose up -d --build
```
The backend does **not** expose a port to the outside — it is reachable only through nginx
at `https://<host>/api/...` (Caddy: HTTPS + password, see the README and `caddy/README.md`). Data lives in the `hex_data` volume.

The image is built from a digest-pinned `python:3.12.15-slim` and installs dependencies with
`pip install --require-hashes` (only the exact locked files). In compose the container has a read-only root
filesystem, no Linux capabilities (`cap_drop: [ALL]`), `no-new-privileges`, `mem_limit: 1g`, `pids_limit: 256`
and a 16 MB `/tmp` tmpfs; `TMPDIR=/app/data/tmp` makes multipart uploads spool into the data volume instead.

The container runs as a regular user `app` (uid 10001), not root. The healthcheck is in the `Dockerfile`
(`HEALTHCHECK` calling `/ping` via `python -c "import urllib.request; …"` — the image has no curl).
A volume from an installation predating this change (root-owned files) must be handed over to the new user once:
```bash
docker compose run --rm --no-deps --user root --entrypoint chown backend -R 10001:10001 /app/data
```

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `DATA_DIR` | `data` | Directory for files, jobs, archive and database |
| `DATABASE_URL` | `sqlite:///<DATA_DIR>/hex.db` | Database URL (SQLAlchemy) |
| `ARCHIVE` | `1` | `0` disables `.gz` copies |
| `JOB_TTL_HOURS` | `0` | Jobs older than this many hours are deleted (at startup and after every upload); `0` = never |
| `CORS_ORIGINS` | *(empty)* | Allowed origins, comma-separated. Empty = CORS disabled — in Docker and with `npm run dev` (Vite proxy) the frontend and API share the same address, so it is not needed |
| `MAX_CUSTOM_TYPES` | `200` | Limit of custom signatures (each one slows down analysis); once reached, `POST /types` → `409` |
| `MAX_CUSTOM_SCAN_TYPES` | `20` | Limit of custom signatures with `scan_inside` (each one costs a search pass); once reached, `POST /types` with `scan_inside` → `409` |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Accepted `Host` headers, comma-separated (DNS rebinding protection); any other host → `400`. Compose sets it to `HEX_HOSTS` + `localhost` (the healthcheck) |
| `ENABLE_DOCS` | `0` | `1` enables `/docs`, `/redoc` and `/openapi.json` (off in production) |
| `ANALYSIS_WORKERS` | `2` | Threads of the dedicated analysis executor (separate from the pool that serves requests) |
| `MAX_QUEUED_JOBS` | `20` | Queued + running analyses; above it `POST /upload` → `503` "Analysis queue is full" |
| `MIN_FREE_MB` | `1024` | Free space required in `DATA_DIR`; below it `POST /upload` → `507` "Not enough free disk space" |
| `TMPDIR` | *(system)* | Where multipart uploads are spooled; the Docker image sets `/app/data/tmp` (created at startup) |

Constants in `main.py`: `MAX_CONTENT_LENGTH` = 100 MB, `PAGE_MAX` = 16 MB (max per byte download).

---

## API Endpoints

`job_id` is 32 hex characters — any other format gets **422**.

**CSRF protection**: every `POST`, `PUT`, `PATCH` and `DELETE` request must carry the
`X-Hex-Analyzer` header (any value, e.g. `1`) — without it **403** `{"detail": "Missing X-Hex-Analyzer header"}`.
`GET` does not need it. A foreign site cannot add such a header without CORS permission, and a plain HTML form
adds no headers at all. The frontend always sends it.

**Host check**: a request whose `Host` header is not in `ALLOWED_HOSTS` gets **400** before anything else runs.

### 1. `GET /ping`
Health check (used by `HEALTHCHECK` in `backend/Dockerfile`).
```json
{ "message": "API is working" }
```

### 2. `POST /upload`
Multipart form with a `file` field. The file name is stripped of directories
(`../../x.bin` → `x.bin`) and of control/format characters (newlines, NUL, bidi overrides such as U+202E,
zero-width characters), and cut to at most 150 bytes of UTF-8 — from the front, so the end and the extension stay.
An empty result becomes `uploaded.bin`.

**Response 202 Accepted** (analysis only queued):
```json
{
  "job_id": "a3f8d9c2b1e4...",
  "status": "queued",
  "meta": {
    "job_id": "a3f8d9c2b1e4...",
    "stored_name": "a3f8d9c2b1e4..._file.bin",
    "filename": "file.bin",
    "size_bytes": 1048576,
    "sha256": null,
    "analysis_ready": false,
    "status": "queued"
  }
}
```
**Errors**: `400` — unknown `Host` or invalid `Content-Length`, `403` — missing `X-Hex-Analyzer` header,
`413` — file larger than 100 MB (a too-large `Content-Length` is rejected before the body is read; in Docker
Caddy and nginx already reject it), `422` — missing `file` field,
`503` — analysis queue full (`MAX_QUEUED_JOBS`), `507` — less than `MIN_FREE_MB` free in `DATA_DIR`.
The `503`/`507` checks also run before the body is read, and nothing is written to disk.

### 3. `GET /jobs/{job_id}`
Job status. Once the analysis finishes, a `result` field is added.

```json
{
  "job_id": "a3f8d9c2b1e4...",
  "stored_name": "a3f8d9c2b1e4..._file.png",
  "filename": "file.png",
  "size_bytes": 400008,
  "sha256": "e3b0c442...",
  "analysis_ready": true,
  "status": "done",
  "result": {
    "sha256": "e3b0c442...",
    "file": {
      "id": 7, "sha256": "e3b0c442...", "size": 400008, "entropy": 7.9995,
      "type": { "id": 1, "name": "PNG image", "extension": "png", "magic": "89504E470D0A1A0A", "offset": 0, "builtin": true },
      "first_seen": "2026-10-23T10:57:19"
    },
    "entropy_profile": [7.95, 7.96, "..."],
    "profile_step": 4096,
    "embedded": [ { "type": { "name": "ZIP archive (also DOCX/JAR/APK)", "...": "..." }, "offset": 10000 } ]
  }
}
```

- `file.type` = `null` when no signature matches
- `entropy_profile` — entropy of successive fragments of `profile_step` bytes (at most 512 points)
- `embedded` — signatures found **inside** the file (offset = start of the embedded file)

**Statuses**: `queued` → `processing` → `done` or `error`.
On `error` the response has an `analysis_error` field — always the generic `"Analysis failed"` (the details,
which could reveal paths or SQL, go only to the server log). Polling should stop then.

**Errors**: `404` — unknown `job_id`.

### 4. `DELETE /jobs/{job_id}`
Deletes the job together with its file in `uploads/` and the archive. Response **204** or **404** (**403** without the `X-Hex-Analyzer` header).
It can also be called during analysis — the analysis then finishes without an error and cleans up whatever it had already written to the database.

### 5. `GET /jobs/{job_id}/bytes?offset=0&length=8388608`
Raw file bytes (`application/octet-stream`).

- `offset` 0…2^62 (default 0)
- `length` 1…16 MB (default 8 MB)
- A request past the end of the file returns an empty body (200); a shorter chunk at the end returns whatever is left.

**Errors**: `404` — unknown `job_id`, `410` — the source file no longer exists, `422` — invalid parameters.

### 6. `GET /jobs/{job_id}/graph?min_similarity=0.05&limit=25`
The file's relation graph, **computed live** — files uploaded later show up in it too.

```json
{
  "center": "f:7",
  "nodes": [
    { "id": "f:7", "kind": "file", "current": true, "label": "file.png", "names": ["copy.png", "file.png"], "names_total": 2,
      "job_id": "a3f8...", "size": 400008, "entropy": 7.99, "type": { "...": "..." } },
    { "id": "t:1", "kind": "type", "label": "PNG image", "extension": "png", "magic": "89504E470D0A1A0A" }
  ],
  "edges": [
    { "source": "f:7", "target": "t:1", "relation": "is_type" },
    { "source": "f:7", "target": "f:9", "relation": "similar", "weight": 0.98, "label": "98%" },
    { "source": "f:7", "target": "t:12", "relation": "contains", "count": 1, "label": "1× from 0x2710" },
    { "source": "f:7", "target": "f:3", "relation": "same_name" }
  ]
}
```

| Relation | Meaning |
|---|---|
| `is_type` | file → its type; files of the same type cluster around the type node (up to `limit` newest) |
| `similar` | Jaccard similarity of the content-defined chunks (`weight` 0–1), only ≥ `min_similarity`. Each file stores a bottom-k sketch of its 2048 smallest block hashes (exact for files up to ~2.5 MB, an estimate above); a graph request scores at most the 200 most-overlapping files |
| `contains` | the file contains a signature of another type |
| `same_name` | same name, different content (e.g. successive firmware versions) |

Identical files (same SHA-256) are **one** node — its names are in `names` (sorted, at most 20) and
`names_total` gives the total count, so a file uploaded under thousands of names does not bloat the response.
The `job_id` in a file node lets you open it (`null` when no upload exists).

**Errors**: `404` — unknown `job_id`, `409` — analysis still running.

### 7. `GET /types`, `POST /types` and `DELETE /types/{id}`
The signature database. `GET` returns a list: `id`, `name`, `extension`, `magic`, `offset`, `builtin`, `scan_inside`
(`builtin: true` = a type from the initial database). `POST` adds a new one — it takes effect in subsequent analyses right away:

```json
{ "name": "My format", "extension": "myf", "magic": "4D 59 46 31", "offset": 0, "scan_inside": true }
```
- `magic` — 1–32 bytes of HEX in any notation (`0x4d:59…`, with spaces, tabs or newlines — all whitespace
  is ignored) — stored as `4D594631`; anything else → **422**.
- `name` (1–120 characters) and `extension` — control/format characters are stripped; `extension` is
  lower-cased and must then match `[a-z0-9._-]{1,16}`, otherwise **422**.
- `scan_inside` (searching inside files) is forced to `false` unless the signature is ≥ 4 bytes and not one
  repeated byte (`00000000` would match everywhere).

Response **201**; **409** when a type with the same `magic` and `offset` already exists, when the
`MAX_CUSTOM_TYPES` limit is reached (only custom types count), or — for a `scan_inside` type — when
`MAX_CUSTOM_SCAN_TYPES` custom scanned types already exist.

`DELETE /types/{id}` deletes a custom signature (together with its hits in the `embedded` table). `id` must be
1…2^31−1 (otherwise **422**). Response **204**; built-in type → **403**, type assigned to analyzed files → **409**,
unknown `id` → **404**.

---

## Modules

### features.py — features in a single pass
`extract_features(path, scan_types) -> Features` reads the file in 1 MB pieces **once** and computes:

- **SHA-256**
- **Shannon entropy** (bits/byte) from the byte histogram (`numpy.bincount`) and the **entropy profile**
  (fragments of `profile_step` bytes, ≤ 512 points)
- **content-defined chunk hashes** (content-defined chunking, 64-bit blake2b):
  a chunk boundary falls where the hash of 8 consecutive bytes has 10 zero bits
  (chunks of 256 B – 4 KB, ~1.2 KB on average). After bytes are inserted into the middle of a file, later boundaries
  fall at the same places in the content, so the chunks after the insertion still match.
  The 8-byte window is computed vectorized (8 shifted `numpy.frombuffer` views).
  Chunks made of a single repeated byte are skipped (zeros/0xFF are in every file).
- **hit verification** — after a signature is found inside a file, further header bytes
  are checked (`VALIDATORS`: ELF, Java class, ZIP, Zstd, XZ, RIFF, OGG, FLAC, TIFF, PSD, CAB, MP4,
  DEX, WASM, UF2, Mach-O, PDF, JPEG). This rejects random 4-byte matches in compressed noise.
- **embedded signatures** — `bytes.find` over overlapping pieces, so a signature on a piece
  boundary is not missed. Up to 2000 raw candidates per type are collected and **validated first**; only then
  is the result capped at 20 valid hits per type — so bare magic bytes in front (decoys) cannot hide
  a real embedded file

The pure functions (`entropy_from_counts`, `jaccard`, `block_hash`) have doctests.
Time on the author's laptop (i7-3740QM): ~5 s per 100 MB with a full signature scan.

Changing the chunk/hit algorithm → bump `FEATURES_VERSION`. At startup the backend compares it
with the `settings` table and recomputes all files whose original still exists
(and the `embedded` list in their `result.json`).

Measured on real files (Fedora):

| Pair | Similarity |
|---|---|
| `ls` ↔ `ls` with 16 bytes replaced | 98% |
| `ls` ↔ `ls` with 100 bytes inserted at the start | 98% |
| PNG ↔ the same PNG with a JAR appended | 93% |
| `ls` ↔ `dir` (compiled separately) | 28% |
| two different PNGs / two different PDFs / `ls` ↔ kernel | 0% |

### analyzer.py
`analyze_file(path, session, job_id, filename) -> dict`
1. Features from `features.py`
2. Type: the **longest** matching signature from `file_types` (with offset)
3. Embedded hits of the file's own type are discarded, and so are hits with the same extension —
   but the extension rule applies only when both types are built-in ("ZIP contains ZIP" is noise —
   every archive entry starts with `PK\x03\x04`); a custom type cannot suppress built-in hits
4. New SHA-256 → a row in `files` + chunks + embedded (one transaction; when the same file is analyzed
   in parallel, the second process catches `IntegrityError` and takes the existing entry)
5. Always a new row in `file_names` (name + `job_id`)

`forget_job()` — on `DELETE`: removes the upload from the database, and when the file has no names left, the file with its chunks as well.

### graph.py
`build_graph(session, file_id, job_exists, min_similarity, limit)` — builds the graph from the API section.
Similarity is computed by a single SQL query (shared chunk hashes via an index), Jaccard = shared / (A + B − shared).

---

## Database

| Table | Contents |
|---|---|
| `file_types` | signatures: `name`, `extension`, `magic` (HEX), `offset`, `scan_inside`, `builtin` |
| `files` | one row per unique content: `sha256` (unique), `size`, `entropy`, `block_count`, `type_id`, `first_seen` |
| `file_names` | every upload: `file_id`, `name`, `job_id` (unique), `uploaded_at` |
| `file_blocks` | `(file_id, h)` — chunk hashes; index on `h` |
| `embedded` | `file_id`, `type_id`, `offset` |

SQLite in WAL mode (reads do not wait for writes), `foreign_keys=ON` (cascading deletes).
The initial signatures (`filetypes_seed.py`) are loaded when `file_types` is empty, with `builtin = true`.
In databases predating the `builtin` column, it is added at startup and signatures from the initial list are marked as built-in —
a one-shot migration that runs only when the column is added, marks at most one exact match per seed entry, and leaves
user copies of seed signatures custom.

At every startup the signature rows are also **sanitised**: `magic` is normalised, `scan_inside` is turned off for
signatures that are not scannable, and invalid rows (left by older versions) are deleted — or, when files still
reference them, kept but never searched for.

**Startup housekeeping**: orphaned uploads and archives (no job directory, older than 1 hour — younger ones may
still be in flight) are swept at startup and after every analysis. In a separate thread (the server responds immediately):
- removing orphaned entries from the database — uploads whose job no longer exists (e.g. deleted during analysis),
- re-analyzing jobs from before this version (result without a `file` field),
- recomputing features when `FEATURES_VERSION` has changed.

The old `signatures.db` file is no longer used.

---

## File analysis workflow

```
1. POST /upload  (queue full → 503, disk almost full → 507, too large → 413 — before the body is read)
2. Streamed write → uploads/<job_id>_<name>  (exceeding 100 MB → 413, file deleted)
3. meta.json (status: queued) → 202 response
4. In the background (dedicated executor, ANALYSIS_WORKERS threads): status processing
5. analyze_file(): features in a single pass, type, store in the database
6. result.json, status done   (or status error + analysis_error "Analysis failed"; details in the log)
7. .gz copy → archive/<job_id>/  (only on success, when ARCHIVE=1)
8. Clean up jobs older than JOB_TTL_HOURS and orphaned uploads/archives older than 1 h
9. GET /jobs/{id} → result; /bytes → bytes for the preview; /graph → relations
```

---

## Security

- `job_id` validated against the pattern `^[0-9a-f]{32}$` — no `../` in paths
- `Host` header checked against `ALLOWED_HOSTS` (`400` otherwise) — DNS rebinding protection in the backend too
- File names reduced to the bare name (no directories), control/format characters stripped, ≤ 150 bytes of UTF-8;
  signature names and extensions are cleaned the same way
- 100 MB limit in the backend (an oversized `Content-Length` is rejected before the body is read),
  101 MiB in Caddy (`request_body max_size`) and nginx (`client_max_body_size`; uploads are streamed, not buffered)
- Bounded analysis queue (`MAX_QUEUED_JOBS` → `503`), free-space check (`MIN_FREE_MB` → `507`),
  dedicated analysis executor (`ANALYSIS_WORKERS`)
- Error details (paths, SQL) only in the server log — `analysis_error` is always `"Analysis failed"`
- `/docs`, `/redoc`, `/openapi.json` disabled unless `ENABLE_DOCS=1`
- CORS disabled by default; enabled only for origins in `CORS_ORIGINS`, without cookies
- CSRF protection: changes (`POST`/`PUT`/`PATCH`/`DELETE`) require the `X-Hex-Analyzer` header
- Custom signature limits (`MAX_CUSTOM_TYPES`, `MAX_CUSTOM_SCAN_TYPES`), duplicates rejected; built-in ones cannot be deleted
- In Docker the backend is not exposed to the host and runs as a regular user (uid 10001), with a read-only root
  filesystem, no capabilities, `no-new-privileges` and memory/process limits
- Dependencies installed only from the hashed lock (`--require-hashes`), base image pinned by digest
- The backend itself has no login — in Docker the password and HTTPS are provided by Caddy (`basic_auth`, see `caddy/README.md`); do not expose it to a network without such a layer

Reporting vulnerabilities: [SECURITY.md](../SECURITY.md).

---

## Tests and lint

```bash
cd backend
pip install -r requirements-dev.txt
pytest              # configured in pyproject.toml
ruff check .        # lint (including bandit: S rules)
ruff format .       # formatting (in CI: ruff format --check .)
```

The tests use `fastapi.testclient.TestClient` and a temporary `DATA_DIR` (`tests/conftest.py`):
- `test_api.py` — endpoints, `job_id` validation, CSRF header, `/types` (limit, deletion),
- `test_graph.py` — relation graph,
- `test_features.py` — file features and hit verification,
- `test_maintenance.py` — `DELETE` before the analysis finishes, cleaning up orphaned entries, recomputing features after a `FEATURES_VERSION` change,
- `test_security.py` — the hardening: Host check, queue/disk limits (`503`/`507`), early `413`, generic analysis errors,
  file/type name cleaning, `/types` validation and limits, decoy hits, startup sanitising and one-shot migration, orphan sweep, docs disabled.

CI (`.github/workflows/ci.yml`) runs the same on every push and pull request.

---

## Extensions and TODO

1. **In-app authentication**: today only a password on the reverse proxy (Caddy)
2. **Rate limiting**: per-client limits (today only a global bound on queued analyses, `MAX_QUEUED_JOBS`)
3. **Monitoring**: Logs, metrics (Prometheus)
4. **Similarity for scattered differences**: separately compiled versions of a program (e.g. `ls` ↔ `dir`)
   share ~80% of their content, but the differences are spread a little everywhere — chunks give ~28% here. A
   fuzzy hash (TLSH / ssdeep) as a second measure would be better
5. **Edges between neighbors** in the graph (today only from the current file)
6. **Batch processing**: Analyzing many files at once

---

## Usage examples

### cURL
```bash
# locally: http://localhost:8000, in Docker: https://localhost/api (curl -u admin:PASSWORD --cacert caddy-hex-root.crt)
# POST/DELETE require the X-Hex-Analyzer header (otherwise 403)
curl -H "X-Hex-Analyzer: 1" -F "file=@/path/to/file.exe" http://localhost:8000/upload
curl http://localhost:8000/jobs/<job_id>
curl -o chunk.bin "http://localhost:8000/jobs/<job_id>/bytes?offset=0&length=1024"
curl -X DELETE -H "X-Hex-Analyzer: 1" http://localhost:8000/jobs/<job_id>
curl -X POST -H "X-Hex-Analyzer: 1" -H "Content-Type: application/json" \
  -d '{"name": "My format", "extension": "myf", "magic": "4D594631"}' http://localhost:8000/types
curl -X DELETE -H "X-Hex-Analyzer: 1" http://localhost:8000/types/<id>
```

### Python - Full workflow
```python
import time
import requests

API = "http://localhost:8000"
CSRF = {"X-Hex-Analyzer": "1"}  # required for POST/DELETE

# 1. Upload
with open("file.bin", "rb") as f:
    job_id = requests.post(f"{API}/upload", files={"file": f}, headers=CSRF).json()["job_id"]

# 2. Status polling — until "done" or "error"
while True:
    status = requests.get(f"{API}/jobs/{job_id}").json()
    if status["status"] == "done":
        print(status["result"])
        break
    if status["status"] == "error":
        raise RuntimeError(status["analysis_error"])
    time.sleep(1)

# 3. Downloading bytes
chunk = requests.get(f"{API}/jobs/{job_id}/bytes", params={"offset": 0, "length": 1024}).content
print(f"Downloaded {len(chunk)} bytes")
```

---

## Contact and support

If you run into problems:
1. Check the server logs (`uvicorn` locally, `docker logs hex-backend` in Docker)
2. Check `status` and `analysis_error` in `GET /jobs/<job_id>`
3. Verify the environment variables (table above)

---

**Documentation version**: 2.1  
**Date**: 2026-10-23

# main.py — FastAPI: upload → background analysis → status + paged bytes
# The original stays in data/uploads/, a .gz copy goes to data/archive/<job_id>/

import gzip
import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    FastAPI,
    File,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi import (
    Path as PathParam,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker
from starlette.middleware.trustedhost import TrustedHostMiddleware

from models import Embedded, FileName, FileType, make_session_factory, normalize_hex, scannable, valid_magic
from models import File as StoredFile  # the name File is taken by FastAPI
from modules.analyzer import analyze_file, features_outdated, forget_job, mark_features_current, refresh_file
from modules.graph import build_graph

logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s: %(message)s")
log = logging.getLogger("hex-analyzer")

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG (environment variables → easy to override in docker-compose)
# ──────────────────────────────────────────────────────────────────────────────
DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
UPLOAD_FOLDER = DATA_DIR / "uploads"
JOBS_DIR = DATA_DIR / "jobs"
ARCHIVE_DIR = DATA_DIR / "archive"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'hex.db'}")

ARCHIVE_ENABLED = os.getenv("ARCHIVE", "1") != "0"  # .gz copy of every file
JOB_TTL_HOURS = float(os.getenv("JOB_TTL_HOURS", "0"))  # 0 = never delete
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]  # disabled by default
MAX_CUSTOM_TYPES = int(os.getenv("MAX_CUSTOM_TYPES", "200"))  # every signature slows down analysis
MAX_CUSTOM_SCAN_TYPES = int(os.getenv("MAX_CUSTOM_SCAN_TYPES", "20"))  # scan_inside costs a pass per signature
# Host header check: a DNS-rebinding page must not reach the API under its own name.
# Behind the proxy this must list the public host name(s).
ALLOWED_HOSTS = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
ENABLE_DOCS = os.getenv("ENABLE_DOCS", "0") == "1"  # /docs, /redoc, /openapi.json — off in production

# Analysis runs in its own small pool (not the shared AnyIO threadpool that serves requests),
# and the queue is bounded — a flood of uploads gets 503 instead of piling up work and disk.
ANALYSIS_WORKERS = int(os.getenv("ANALYSIS_WORKERS", "2"))
MAX_QUEUED_JOBS = int(os.getenv("MAX_QUEUED_JOBS", "20"))  # queued + running
MIN_FREE_MB = int(os.getenv("MIN_FREE_MB", "1024"))  # refuse uploads below this much free space in DATA_DIR
ORPHAN_GRACE_S = 3600  # an upload without a job dir younger than this may still be in flight

MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100 MB (nginx has the same limit)
CHUNK = 1024 * 1024  # 1 MB at a time when writing an upload
PAGE_MAX = 16 * 1024 * 1024  # 16 MB max per bytes request

# job_id is uuid4().hex — reject anything else (no "../" in paths)
JobId = Annotated[str, PathParam(pattern=r"^[0-9a-f]{32}$")]

_executor: ThreadPoolExecutor | None = None  # created in lifespan
_jobs_lock = threading.Lock()
_jobs_pending = 0  # queued + running analyses


# ──────────────────────────────────────────────────────────────────────────────
# APPLICATION
# ──────────────────────────────────────────────────────────────────────────────
def prepare_dirs() -> None:
    for d in (UPLOAD_FOLDER, JOBS_DIR, ARCHIVE_DIR):
        d.mkdir(parents=True, exist_ok=True)
    # In Docker TMPDIR points into the data volume: multipart uploads spool there instead of
    # into RAM (/tmp is a tmpfs on a read-only root fs). The dir must exist before first use.
    if tmpdir := os.getenv("TMPDIR"):
        Path(tmpdir).mkdir(parents=True, exist_ok=True)
        tempfile.tempdir = None  # drop a cached fallback, re-read TMPDIR on next use


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _executor
    prepare_dirs()
    app.state.Session = make_session_factory(DATABASE_URL)
    _executor = ThreadPoolExecutor(max_workers=ANALYSIS_WORKERS, thread_name_prefix="analysis")
    purge_old_jobs()
    # post-upgrade maintenance — in the background, the server starts right away
    threading.Thread(target=startup_maintenance, args=(app.state.Session,), daemon=True).start()
    try:
        yield
    finally:
        # running analyses finish, queued ones are dropped — requeue_unfinished() resumes them on the next start
        _executor.shutdown(wait=True, cancel_futures=True)


app = FastAPI(
    title="Hex Analyzer (FastAPI)",
    version="2.1.0",
    lifespan=lifespan,
    docs_url="/docs" if ENABLE_DOCS else None,
    redoc_url="/redoc" if ENABLE_DOCS else None,
    openapi_url="/openapi.json" if ENABLE_DOCS else None,
)

# CORS is usually unnecessary: in Docker (Caddy → nginx) and in `npm run dev` (Vite proxy)
# the frontend and the API share one origin. Enable it only via CORS_ORIGINS.
if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "X-Hex-Analyzer"],
    )

# CSRF protection: changes (POST/DELETE) require the X-Hex-Analyzer header.
# A foreign site can submit an HTML form (no headers) or a fetch with the header —
# but the latter needs CORS approval, which we don't give. The frontend always sends it.
CSRF_HEADER = "x-hex-analyzer"


@app.middleware("http")
async def limit_body_and_load(request, call_next):
    """Cheap rejections BEFORE the body is read — FastAPI spools the whole multipart body
    to disk before the endpoint runs (nginx has the same size limit, `npm run dev` / uvicorn alone don't)."""
    length = request.headers.get("content-length")
    if length is not None:
        if not length.isdigit():
            return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
        if int(length) > MAX_CONTENT_LENGTH + 1024 * 1024:  # + multipart overhead
            return JSONResponse({"detail": "File too large"}, status_code=413)
    if request.method == "POST" and request.url.path == "/upload":
        if length is None:
            # chunked bodies have no length to check up front; browsers and curl always send one
            return JSONResponse({"detail": "Content-Length required"}, status_code=411)
        try:
            _check_capacity()
        except HTTPException as e:
            return JSONResponse({"detail": e.detail}, status_code=e.status_code)
    return await call_next(request)


@app.middleware("http")
async def require_csrf_header(request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and CSRF_HEADER not in request.headers:
        return JSONResponse({"detail": "Missing X-Hex-Analyzer header"}, status_code=403)
    return await call_next(request)


# Middleware order: the last added runs first → Host check, CSRF header, then size/load limits.
# Unknown Host → 400 before anything else runs.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────
def _job_dir(job_id: str) -> Path:
    return JOBS_DIR / job_id


def _write_json(path: Path, obj: Any) -> None:
    """Atomic write: temp file first, then os.replace (a reader never sees half a file).
    fsync before the rename — otherwise a power cut can leave an empty file under the final name."""
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_meta(job_id: str) -> dict:
    meta_p = _job_dir(job_id) / "meta.json"
    if not meta_p.exists():
        raise HTTPException(status_code=404, detail="Unknown job_id")
    return _read_json(meta_p)


def strip_controls(text: str) -> str:
    """Drops control and format characters (Unicode category C*): NUL, newlines, bidi overrides
    (U+202E makes 'gpj.exe' look like 'exe.jpg'), zero-width characters, lone surrogates."""
    return "".join(c for c in text if not unicodedata.category(c).startswith("C"))


def _safe_filename(raw: str | None) -> str:
    """Bare name without directories ('../../x' → 'x') and control characters, ≤ 150 bytes of UTF-8
    (the filesystem limit is 255 bytes, not characters). The END is kept — it holds the extension."""
    name = Path(strip_controls(raw or "")).name.strip()
    # cut from the front; 'ignore' drops the partial character the cut may leave at the start
    name = name.encode("utf-8")[-150:].decode("utf-8", "ignore").strip()
    return name or "uploaded.bin"


def archive_copy_gzip(src_path: Path, job_id: str, sha256: str) -> None:
    """Compressed copy to archive/<job_id>/input.bin.gz (the original stays)."""
    job_archive = ARCHIVE_DIR / job_id
    job_archive.mkdir(parents=True, exist_ok=True)
    dst = job_archive / "input.bin.gz"
    # level 6: almost the size of 9 at a fraction of the CPU time
    with src_path.open("rb") as f_in, gzip.open(dst, "wb", compresslevel=6) as f_out:
        shutil.copyfileobj(f_in, f_out, length=CHUNK)
    _write_json(
        job_archive / "archive_meta.json",
        {"source": src_path.name, "sha256_source": sha256, "size_gz": dst.stat().st_size},
    )


def _job_exists(job_id: str) -> bool:
    return (_job_dir(job_id) / "meta.json").exists()


def delete_job(job_id: str) -> bool:
    """Removes everything a job left behind: upload, job directory, archive and DB entry."""
    job_dir = _job_dir(job_id)
    if not job_dir.exists():
        return False
    with app.state.Session() as session:
        forget_job(session, job_id)
    for f in UPLOAD_FOLDER.glob(f"{job_id}_*"):
        f.unlink(missing_ok=True)
    # a running analysis may write meta.json while the tree is being removed — retry so no
    # "zombie" job directory survives (the analysis itself gives up once the upload is gone)
    for _ in range(5):
        shutil.rmtree(job_dir, ignore_errors=True)
        if not job_dir.exists():
            break
        time.sleep(0.05)
    shutil.rmtree(ARCHIVE_DIR / job_id, ignore_errors=True)
    return True


def purge_old_jobs() -> None:
    """Cleans up jobs older than JOB_TTL_HOURS (when TTL > 0) and leftovers of jobs that are gone.

    One bad entry (permissions, a race with DELETE) must not stop the rest of the cleanup."""
    if JOB_TTL_HOURS > 0:
        cutoff = time.time() - JOB_TTL_HOURS * 3600
        for job_dir in JOBS_DIR.iterdir():
            try:
                if job_dir.is_dir() and job_dir.stat().st_mtime < cutoff:
                    log.info("Deleting old job %s", job_dir.name)
                    delete_job(job_dir.name)
            except Exception:
                log.exception("Failed to delete old job %s", job_dir.name)
    _purge_orphans()


def _purge_orphans() -> None:
    """Uploads and archives whose job directory no longer exists (crash, interrupted DELETE).
    Only older than ORPHAN_GRACE_S: an upload is written before its job directory is created."""
    cutoff = time.time() - ORPHAN_GRACE_S
    entries = [(p, p.name.split("_", 1)[0]) for p in UPLOAD_FOLDER.iterdir()]
    entries += [(p, p.name) for p in ARCHIVE_DIR.iterdir()]
    for path, job_id in entries:
        try:
            if _job_dir(job_id).exists() or path.lstat().st_mtime >= cutoff:
                continue
            log.info("Removing orphaned %s", path)
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
        except Exception:
            log.exception("Failed to remove orphaned %s", path)
    # job directories whose upload is gone (DELETE racing with a write of meta.json)
    for job_dir in JOBS_DIR.iterdir():
        try:
            if not job_dir.is_dir() or job_dir.stat().st_mtime >= cutoff:
                continue
            if not any(UPLOAD_FOLDER.glob(f"{job_dir.name}_*")):
                log.info("Removing job directory without upload %s", job_dir.name)
                shutil.rmtree(job_dir)
        except Exception:
            log.exception("Failed to remove orphaned %s", job_dir)


# ──────────────────────────────────────────────────────────────────────────────
# BACKGROUND ANALYSIS (in _executor — a few dedicated threads, the server doesn't block)
# ──────────────────────────────────────────────────────────────────────────────
def _check_capacity() -> None:
    """503 when the analysis queue is full, 507 when the data volume is almost full."""
    if _jobs_pending >= MAX_QUEUED_JOBS:
        raise HTTPException(status_code=503, detail="Analysis queue is full, try again later")
    if shutil.disk_usage(DATA_DIR).free < MIN_FREE_MB * 1024 * 1024:
        raise HTTPException(status_code=507, detail="Not enough free disk space")


def _reserve_slot() -> None:
    global _jobs_pending
    with _jobs_lock:  # check + increment atomically, the middleware check is only a fast path
        _check_capacity()
        _jobs_pending += 1


def _release_slot(*_) -> None:
    global _jobs_pending
    with _jobs_lock:
        _jobs_pending -= 1


def _analysis_job(job_id: str, file_path: Path, Session: sessionmaker) -> None:
    try:
        run_analysis(job_id, file_path, Session)
    except Exception:
        log.exception("Analysis job %s crashed", job_id)
    try:
        purge_old_jobs()
    except Exception:
        log.exception("Purging old jobs failed")


def run_analysis(job_id: str, file_path: Path, Session: sessionmaker, archive: bool = ARCHIVE_ENABLED) -> None:
    try:
        _run_analysis(job_id, file_path, Session, archive)
    except FileNotFoundError:
        if _job_exists(job_id):
            raise
        # the job was deleted (DELETE) before or during analysis — not an error,
        # just clean up whatever the analysis managed to write to the DB
        log.info("Job %s deleted during analysis", job_id)
        with Session() as session:
            forget_job(session, job_id)


def _run_analysis(job_id: str, file_path: Path, Session: sessionmaker, archive: bool) -> None:
    meta_p = _job_dir(job_id) / "meta.json"
    meta = _read_json(meta_p)
    meta["status"] = "processing"
    _write_json(meta_p, meta)

    try:
        with Session() as session:
            result = analyze_file(file_path, session, job_id, meta["filename"])
    except Exception as e:
        if not _job_exists(job_id):
            raise FileNotFoundError(job_id) from e
        log.exception("Analysis of %s failed", job_id)
        # details stay in the server log — exception text can reveal paths and SQL
        meta.update(status="error", analysis_error="Analysis failed")
        _write_json(meta_p, meta)
        return

    if not _job_exists(job_id):
        raise FileNotFoundError(job_id)

    _write_json(_job_dir(job_id) / "result.json", result)
    meta.update(sha256=result["sha256"], status="done", analysis_ready=True)
    _write_json(meta_p, meta)

    if archive:
        try:
            archive_copy_gzip(file_path, job_id, result["sha256"])
        except OSError:
            log.exception("Archiving %s failed", job_id)


def reanalyze_legacy_jobs(Session: sessionmaker) -> None:
    """Re-analyses jobs from before the new DB model (result.json without a "file" field)."""
    for meta_p in JOBS_DIR.glob("*/meta.json"):
        job_id = meta_p.parent.name
        result_p = meta_p.parent / "result.json"
        try:
            meta = _read_json(meta_p)
            if meta.get("status") != "done" or "file" in _read_json(result_p):
                continue
            file_path = UPLOAD_FOLDER / meta["stored_name"]
            if file_path.exists():
                log.info("Re-analysing legacy job %s", job_id)
                run_analysis(job_id, file_path, Session, archive=False)
        except Exception:
            log.exception("Failed to re-analyse %s", job_id)


def refresh_outdated_features(Session: sessionmaker) -> None:
    """When the block/hit algorithm (FEATURES_VERSION) has changed — recomputes the files in the DB."""
    with Session() as session:
        if not features_outdated(session):
            return
        files = session.scalars(select(StoredFile)).all()
        log.info("Recomputing features of %d files (new algorithm version)", len(files))
        for file in files:
            live = [n for n in file.names if _job_exists(n.job_id)]
            path = next((p for n in live if (p := _stored_path(n.job_id)) is not None), None)
            if path is None:
                continue  # original missing — the file keeps its old blocks
            try:
                fresh = refresh_file(session, file, path)
            except Exception:
                session.rollback()
                log.exception("Failed to recompute file %s", file.sha256)
                continue
            for n in live:  # result.json of this file's jobs: new list of embedded signatures
                result_p = _job_dir(n.job_id) / "result.json"
                if result_p.exists():
                    _write_json(result_p, _read_json(result_p) | fresh)
        mark_features_current(session)


def _stored_path(job_id: str) -> Path | None:
    """The job's original in uploads/, or None (missing file, unreadable or damaged meta.json)."""
    try:
        p = UPLOAD_FOLDER / Path(_read_json(_job_dir(job_id) / "meta.json")["stored_name"]).name
    except (OSError, ValueError, KeyError, TypeError):
        log.warning("Skipping job %s: unreadable meta.json", job_id)
        return None
    return p if p.exists() else None


def forget_orphans(Session: sessionmaker) -> None:
    """Removes DB entries whose job no longer exists (e.g. an interrupted DELETE)."""
    with Session() as session:
        orphans = [n.job_id for n in session.scalars(select(FileName)) if not _job_exists(n.job_id)]
        for job_id in orphans:
            forget_job(session, job_id)
    if orphans:
        log.info("Removed %d orphaned entries", len(orphans))


def requeue_unfinished(Session: sessionmaker) -> None:
    """Jobs left "queued"/"processing" by a restart are submitted again (or marked failed
    when their upload is gone) — otherwise they would wait forever."""
    global _jobs_pending
    for meta_p in JOBS_DIR.glob("*/meta.json"):
        job_id = meta_p.parent.name
        try:
            meta = _read_json(meta_p)
            if meta.get("status") not in ("queued", "processing"):
                continue
            path = UPLOAD_FOLDER / meta["stored_name"]
            if not path.exists():
                meta.update(status="error", analysis_error="Analysis failed")
                _write_json(meta_p, meta)
                continue
            log.info("Re-queuing unfinished job %s", job_id)
            with _jobs_lock:  # counted like any upload, but never refused — it is already accepted
                _jobs_pending += 1
            _executor.submit(_analysis_job, job_id, path, Session).add_done_callback(_release_slot)
        except Exception:
            log.exception("Could not re-queue %s", job_id)


def startup_maintenance(Session: sessionmaker) -> None:
    requeue_unfinished(Session)
    forget_orphans(Session)
    reanalyze_legacy_jobs(Session)
    try:
        refresh_outdated_features(Session)
    except Exception:
        log.exception("Feature recomputation failed")


# ──────────────────────────────────────────────────────────────────────────────
# POST /upload — stores the file, returns job_id + meta (202: analysis only queued)
# ──────────────────────────────────────────────────────────────────────────────
@app.post("/upload", status_code=202)
def upload_file(file: Annotated[UploadFile, File()]):
    # `def`, not `async def`: disk writes block, so let them block a pool thread,
    # not the event loop (otherwise the whole server stalls during the write).
    _reserve_slot()  # 503 / 507 before anything is written
    filename = _safe_filename(file.filename)
    job_id = uuid.uuid4().hex
    dest = UPLOAD_FOLDER / f"{job_id}_{filename}"

    size = 0
    try:
        with dest.open("wb") as out:
            while chunk := file.file.read(CHUNK):
                size += len(chunk)
                if size > MAX_CONTENT_LENGTH:
                    raise HTTPException(status_code=413, detail="File too large")
                out.write(chunk)

        meta = {
            "job_id": job_id,
            "stored_name": dest.name,  # name in uploads/
            "filename": filename,  # original name for the UI
            "size_bytes": size,
            "sha256": None,  # computed by run_analysis
            "analysis_ready": False,
            "status": "queued",
        }
        _job_dir(job_id).mkdir(parents=True)
        _write_json(_job_dir(job_id) / "meta.json", meta)
        future = _executor.submit(_analysis_job, job_id, dest, app.state.Session)
    except BaseException:
        # nothing half-made may stay behind: no job → nobody would ever delete the upload
        _release_slot()
        dest.unlink(missing_ok=True)
        shutil.rmtree(_job_dir(job_id), ignore_errors=True)
        raise
    future.add_done_callback(_release_slot)
    return {"job_id": job_id, "status": "queued", "meta": meta}


# ──────────────────────────────────────────────────────────────────────────────
# GET /jobs/{job_id} — status + meta + (when ready) analysis result
# DELETE /jobs/{job_id} — deletes the job and its files
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/jobs/{job_id}")
def job_status(job_id: JobId):
    meta = _load_meta(job_id)
    result_p = _job_dir(job_id) / "result.json"
    if result_p.exists():
        meta["result"] = _read_json(result_p)
    return meta


@app.delete("/jobs/{job_id}", status_code=204)
def job_delete(job_id: JobId):
    if not delete_job(job_id):
        raise HTTPException(status_code=404, detail="Unknown job_id")


# ──────────────────────────────────────────────────────────────────────────────
# GET /jobs/{job_id}/bytes?offset=&length= — a slice of the file (binary)
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/jobs/{job_id}/bytes")
def job_bytes(
    job_id: JobId,
    offset: int = Query(0, ge=0, le=2**62),  # seek() past 2**63 overflows → 500
    length: int = Query(8 * 1024 * 1024, ge=1, le=PAGE_MAX),
):
    meta = _load_meta(job_id)
    file_path = UPLOAD_FOLDER / meta["stored_name"]
    if not file_path.exists():
        raise HTTPException(status_code=410, detail="Source file no longer available")

    with file_path.open("rb") as f:
        f.seek(offset)
        chunk = f.read(length)  # past the end of the file read() just returns less / b""

    return Response(chunk, media_type="application/octet-stream")


# ──────────────────────────────────────────────────────────────────────────────
# GET /jobs/{job_id}/graph — file relations (computed live)
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/jobs/{job_id}/graph")
def job_graph(
    job_id: JobId,
    min_similarity: float = Query(0.05, ge=0, le=1),
    limit: int = Query(25, ge=1, le=200),
):
    _load_meta(job_id)  # 404 if the job doesn't exist
    with app.state.Session() as session:
        upload = session.scalar(select(FileName).where(FileName.job_id == job_id))
        if upload is None:
            raise HTTPException(status_code=409, detail="Analysis not finished")
        return build_graph(session, upload.file_id, _job_exists, min_similarity, limit)


# ──────────────────────────────────────────────────────────────────────────────
# GET/POST /types — signature database (magic bytes)
# ──────────────────────────────────────────────────────────────────────────────
class NewFileType(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    extension: str = Field(min_length=1, max_length=16)
    magic: str = Field(description="HEX, e.g. '89 50 4E 47' or '0x7f454c46'")
    offset: int = Field(0, ge=0, le=32768)
    scan_inside: bool = False

    @field_validator("name")
    @classmethod
    def _clean_name(cls, v: str) -> str:
        v = strip_controls(v).strip()
        if not v:
            raise ValueError("name: must not be empty")
        return v

    @field_validator("extension")
    @classmethod
    def _clean_extension(cls, v: str) -> str:
        v = strip_controls(v).strip().lower()
        if not re.fullmatch(r"[a-z0-9._-]{1,16}", v):
            raise ValueError("extension: 1–16 characters a-z 0-9 . _ -")
        return v

    @field_validator("magic")
    @classmethod
    def _valid_hex(cls, v: str) -> str:
        h = normalize_hex(v)
        if not valid_magic(h):
            raise ValueError("magic: even number of HEX digits, 1–32 bytes")
        return h


@app.get("/types")
def list_types():
    with app.state.Session() as session:
        return [
            t.to_dict() | {"scan_inside": t.scan_inside}
            for t in session.scalars(select(FileType).order_by(FileType.id))
        ]


@app.post("/types", status_code=201)
def add_type(body: NewFileType):
    # searching inside files only for signatures ≥ 4 bytes, not one repeated byte — others are nothing but false hits
    scan = body.scan_inside and scannable(bytes.fromhex(body.magic))
    with app.state.Session() as session:
        custom = session.scalar(select(func.count()).select_from(FileType).where(~FileType.builtin))
        if custom >= MAX_CUSTOM_TYPES:
            raise HTTPException(status_code=409, detail=f"Limit of {MAX_CUSTOM_TYPES} custom types reached")
        if scan:
            scanned = session.scalar(
                select(func.count()).select_from(FileType).where(~FileType.builtin, FileType.scan_inside)
            )
            if scanned >= MAX_CUSTOM_SCAN_TYPES:
                raise HTTPException(
                    status_code=409, detail=f"Limit of {MAX_CUSTOM_SCAN_TYPES} custom scanned types reached"
                )
        if session.scalar(select(FileType.id).where(FileType.magic == body.magic, FileType.offset == body.offset)):
            raise HTTPException(status_code=409, detail="A type with this signature and offset already exists")
        t = FileType(name=body.name, extension=body.extension, magic=body.magic, offset=body.offset, scan_inside=scan)
        session.add(t)
        session.commit()
        return t.to_dict() | {"scan_inside": t.scan_inside}


@app.delete("/types/{type_id}", status_code=204)
def delete_type(type_id: Annotated[int, PathParam(ge=1, le=2**31 - 1)]):  # SQLite overflows past int64 → 500
    with app.state.Session() as session:
        t = session.get(FileType, type_id)
        if t is None:
            raise HTTPException(status_code=404, detail="Unknown type")
        if t.builtin:
            raise HTTPException(status_code=403, detail="Built-in types cannot be deleted")
        if session.scalar(select(func.count()).select_from(StoredFile).where(StoredFile.type_id == type_id)):
            raise HTTPException(status_code=409, detail="Type is assigned to analysed files")
        session.query(Embedded).filter(Embedded.type_id == type_id).delete()
        session.delete(t)
        session.commit()


# ──────────────────────────────────────────────────────────────────────────────
# GET /ping — liveness check (used by HEALTHCHECK in backend/Dockerfile)
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/ping")
async def ping():  # async: answers on the event loop even when every pool thread is busy
    return {"message": "API is working"}

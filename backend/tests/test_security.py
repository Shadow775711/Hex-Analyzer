"""Hardening: input validation, resource limits, error disclosure, host check, disk hygiene."""

import gzip
import inspect
import os
import tempfile
import threading
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select

import main
from conftest import CSRF, wait_for_job
from models import File, FileType, Setting, make_session_factory, normalize_hex
from modules import analyzer
from modules import features as F
from modules.analyzer import detect_type, forget_job
from modules.filetypes_seed import SEED_TYPES


def _multipart(filename: str, data: bytes) -> tuple[bytes, dict]:
    """Hand-made body — HTTP clients escape odd characters in file names, an attacker doesn't."""
    b = "hexboundary1234"
    body = (
        (
            f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        + data
        + f"\r\n--{b}--\r\n".encode()
    )
    return body, {"Content-Type": f"multipart/form-data; boundary={b}"}


def _upload_raw(client, filename: str, data: bytes) -> dict:
    body, headers = _multipart(filename, data)
    r = client.post("/upload", content=body, headers=headers)
    assert r.status_code == 202, r.text
    return wait_for_job(client, r.json()["job_id"])


def _wait_idle(timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while main._jobs_pending:
        assert time.monotonic() < deadline
        time.sleep(0.02)


def _snapshot():
    return set(main.UPLOAD_FOLDER.iterdir()), set(main.JOBS_DIR.iterdir())


# ── 1. signatures ────────────────────────────────────────────────────────────
def test_normalize_hex_removes_all_whitespace():
    assert normalize_hex("0x4d:5a") == "4D5A"
    assert normalize_hex(" 4D\t5A\n90\r\x0b00 ") == "4D5A9000"


class TestSignatureValidation:
    def test_whitespace_is_not_stored(self, client):
        r = client.post("/types", json={"name": "tabs", "extension": "tab", "magic": "7A\t11\n22 33"})
        assert r.status_code == 201, r.text
        assert r.json()["magic"] == "7A112233"
        client.delete(f"/types/{r.json()['id']}")

    @pytest.mark.parametrize("magic", ["٣٣", "4D5", "4D 5", "GG", "0x", "\t", "4D-5A"])
    def test_bad_hex_rejected(self, client, magic):
        r = client.post("/types", json={"name": "x", "extension": "x", "magic": magic})
        assert r.status_code == 422

    @pytest.mark.parametrize("magic", ["00000000", "FFFFFFFFFF", "7A\t7A\t7A"])
    def test_repeated_or_short_magic_not_scanned(self, client, magic):
        r = client.post("/types", json={"name": "rep", "extension": "rep", "magic": magic, "scan_inside": True})
        assert r.status_code == 201, r.text
        assert r.json()["scan_inside"] is False
        client.delete(f"/types/{r.json()['id']}")

    def test_invalid_legacy_row_matches_nothing(self):
        t = FileType(id=1, name="legacy", extension="x", magic="XYZ", offset=0)
        assert t.magic_bytes == b""
        assert detect_type(b"anything", [t]) is None

    def test_detect_type_sorts_by_byte_length(self):
        short = FileType(id=1, name="short", extension="a", magic="4D5A", offset=0)
        longer = FileType(id=2, name="long", extension="b", magic="4D5A90", offset=0)
        assert detect_type(b"MZ\x90\x00", [short, longer]).name == "long"


def test_startup_sanitizes_types(tmp_path):
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    make_session_factory(url)
    engine = create_engine(url)
    with engine.begin() as c:
        ins = "INSERT INTO file_types (id, name, extension, magic, offset, scan_inside, builtin) VALUES "
        c.exec_driver_sql(ins + "(901, 'tabbed', 'tb', '4D\t59\n4621', 0, 1, 0)")
        c.exec_driver_sql(ins + "(902, 'garbage', 'gb', 'XYZ', 0, 0, 0)")
        c.exec_driver_sql(ins + "(903, 'garbage used', 'gu', 'QQ', 0, 1, 0)")
        c.exec_driver_sql(ins + "(904, 'zeros', 'z', '00000000', 0, 1, 0)")
        c.exec_driver_sql("INSERT INTO files (sha256, size, entropy, block_count, type_id) VALUES ('ab', 1, 0, 0, 903)")
    Session = make_session_factory(url)  # second startup
    with Session() as s:
        rows = {t.id: t for t in s.scalars(select(FileType).where(FileType.id > 900))}
    assert set(rows) == {901, 903, 904}  # unreferenced garbage deleted
    assert (rows[901].magic, rows[901].scan_inside) == ("4D594621", True)
    assert rows[903].scan_inside is False  # kept for its file, never scanned
    assert rows[904].scan_inside is False


# ── 2. built-in migration ────────────────────────────────────────────────────
def test_builtin_migration_is_one_shot_and_exact(tmp_path):
    url = f"sqlite:///{tmp_path / 'old.db'}"
    make_session_factory(url)
    png = next(s for s in SEED_TYPES if s[1] == "png")
    engine = create_engine(url)
    with engine.begin() as c:  # a database from before the builtin column
        c.exec_driver_sql("DELETE FROM file_types")
        c.exec_driver_sql("ALTER TABLE file_types DROP COLUMN builtin")
        ins = "INSERT INTO file_types (name, extension, magic, offset, scan_inside) VALUES (?, ?, ?, ?, 1)"
        c.exec_driver_sql(ins, ("evil", "png", png[2], 0))  # attacker's copy, different name
        c.exec_driver_sql(ins, png[:4])
        c.exec_driver_sql(ins, png[:4])  # exact duplicate of the seed row
    Session = make_session_factory(url)
    with Session() as s:
        flags = [(t.name, t.builtin) for t in s.scalars(select(FileType).order_by(FileType.id))]
        assert flags == [("evil", False), (png[0], True), (png[0], False)]
        s.add(FileType(name=png[0], extension="png", magic=png[2], offset=0))  # added later
        s.commit()
    Session = make_session_factory(url)  # next startup: no promotion any more
    with Session() as s:
        assert sum(t.builtin for t in s.scalars(select(FileType))) == 1


def test_duplicate_signature_rejected(client):
    r = client.post("/types", json={"name": "fake png", "extension": "png", "magic": "89504E470D0A1A0A"})
    assert r.status_code == 409
    ok = client.post("/types", json={"name": "png at 1", "extension": "png", "magic": "89504E470D0A1A0A", "offset": 1})
    assert ok.status_code == 201
    client.delete(f"/types/{ok.json()['id']}")


# ── 3. resource limits ───────────────────────────────────────────────────────
def test_queue_full_returns_503_without_writing(client, monkeypatch):
    monkeypatch.setattr(main, "MAX_QUEUED_JOBS", 0)
    before = _snapshot()
    r = client.post("/upload", files={"file": ("q.bin", b"x" * 1000)})
    assert (r.status_code, r.json()) == (503, {"detail": "Analysis queue is full, try again later"})
    assert _snapshot() == before


def test_low_disk_returns_507(client, monkeypatch):
    monkeypatch.setattr(main, "MIN_FREE_MB", 10**12)
    before = _snapshot()
    r = client.post("/upload", files={"file": ("d.bin", b"x" * 1000)})
    assert (r.status_code, r.json()) == (507, {"detail": "Not enough free disk space"})
    assert _snapshot() == before


def test_analysis_runs_in_bounded_executor(client, monkeypatch):
    assert main._executor._max_workers == main.ANALYSIS_WORKERS
    started, release = threading.Event(), threading.Event()

    def slow(*_args, **_kw):
        started.set()
        release.wait(10)

    monkeypatch.setattr(main, "run_analysis", slow)
    t0 = time.monotonic()
    r = client.post("/upload", files={"file": ("slow.bin", b"x" * 100)})
    assert r.status_code == 202 and time.monotonic() - t0 < 5  # the response doesn't wait for the analysis
    assert started.wait(5)
    assert main._jobs_pending >= 1
    release.set()
    _wait_idle()
    assert main._jobs_pending == 0
    client.delete(f"/jobs/{r.json()['job_id']}")


def test_ping_is_async():
    assert inspect.iscoroutinefunction(main.ping)


def test_custom_scan_type_limit(client, monkeypatch):
    monkeypatch.setattr(main, "MAX_CUSTOM_SCAN_TYPES", 0)
    r = client.post("/types", json={"name": "s", "extension": "s", "magic": "A1B2C3D4", "scan_inside": True})
    assert r.status_code == 409
    r = client.post("/types", json={"name": "s", "extension": "s", "magic": "A1B2C3D4"})
    assert r.status_code == 201  # without scanning it's fine
    client.delete(f"/types/{r.json()['id']}")


def test_archive_uses_level_6(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ARCHIVE_DIR", tmp_path)
    src = tmp_path / "src.bin"
    src.write_bytes(os.urandom(1000))
    main.archive_copy_gzip(src, "c" * 32, "00")
    raw = (tmp_path / ("c" * 32) / "input.bin.gz").read_bytes()
    assert raw[8] == 0  # gzip XFL: 2 = level 9, 4 = level 1, 0 = anything in between
    assert gzip.decompress(raw) == src.read_bytes()


# ── 4. input that used to end in a 500 ───────────────────────────────────────
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a\x00b.png", "ab.png"),
        ("photo\u202egnp.exe", "photognp.exe"),
        ("x\u200b\u2066y\u2069.bin", "xy.bin"),
        ("\x00\x01\u202e", "uploaded.bin"),
    ],
)
def test_control_chars_stripped_from_filename(client, raw, expected):
    assert _upload_raw(client, raw, b"data")["filename"] == expected


def test_long_utf8_filename_truncated(client):
    job = _upload_raw(client, "\U0001f600" * 100 + "ż.png", b"data")
    name = job["filename"]
    assert len(name.encode()) <= 150 and name.endswith("ż.png") and name.startswith("\U0001f600")


def test_type_name_and_extension_cleaned(client):
    r = client.post("/types", json={"name": "My\u202e type\x00", "extension": "Ab\u200bC", "magic": "C0FFEE01"})
    assert r.status_code == 201, r.text
    assert (r.json()["name"], r.json()["extension"]) == ("My type", "abc")
    client.delete(f"/types/{r.json()['id']}")


@pytest.mark.parametrize(("name", "ext"), [("\u200b\x00", "x"), ("ok", "a/b"), ("ok", "<svg>"), ("ok", "\u202e")])
def test_bad_type_name_or_extension(client, name, ext):
    assert client.post("/types", json={"name": name, "extension": ext, "magic": "C0FFEE02"}).status_code == 422


def test_huge_bytes_offset(client, upload):
    job_id, _ = upload("off.bin", b"12345")
    assert client.get(f"/jobs/{job_id}/bytes", params={"offset": 2**63}).status_code == 422
    r = client.get(f"/jobs/{job_id}/bytes", params={"offset": 2**62})
    assert (r.status_code, r.content) == (200, b"")


@pytest.mark.parametrize("type_id", ["0", "-1", str(2**31), str(2**70)])
def test_delete_type_bad_id(client, type_id):
    assert client.delete(f"/types/{type_id}").status_code == 422


# ── 5. embedded decoys ───────────────────────────────────────────────────────
def test_decoys_dont_hide_real_embedded_file(tmp_path):
    blob = bytearray(os.urandom(200_000))
    for i in range(50):  # bare magic followed by a nonsense header
        blob[1000 + i * 100 : 1000 + i * 100 + 10] = bytes.fromhex("504B0304FF0000007700")
    blob[100_000:100_010] = bytes.fromhex("504B0304140000000800")
    p = tmp_path / "decoys.bin"
    p.write_bytes(bytes(blob))
    assert F.extract_features(p, [F.ScanType(1, bytes.fromhex("504B0304"), 0, "zip")]).embedded == [(1, 100_000)]


def test_valid_hits_capped(tmp_path):
    blob = bytearray(os.urandom(100_000))
    for i in range(30):
        blob[1000 + i * 100 : 1000 + i * 100 + 10] = bytes.fromhex("504B0304140000000800")
    p = tmp_path / "many.bin"
    p.write_bytes(bytes(blob))
    hits = F.extract_features(p, [F.ScanType(1, bytes.fromhex("504B0304"), 0, "zip")]).embedded
    assert hits == [(1, 1000 + i * 100) for i in range(F.MAX_HITS_PER_TYPE)]


def test_custom_type_cannot_suppress_builtin_hits(client, upload):
    r = client.post("/types", json={"name": "Not an ELF", "extension": "elf", "magic": "DEADBEEF0102"})
    assert r.status_code == 201
    blob = bytearray(bytes.fromhex("DEADBEEF0102") + os.urandom(100_000))
    blob[50_000:50_007] = bytes.fromhex("7F454C46020101")
    _, job = upload("disguised.bin", bytes(blob))
    assert job["result"]["file"]["type"]["name"] == "Not an ELF"
    assert [(e["type"]["extension"], e["offset"]) for e in job["result"]["embedded"]] == [("elf", 50_000)]


# ── 6. error disclosure and DB races ─────────────────────────────────────────
def test_analysis_error_is_generic(client, upload, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("/secret/path SELECT * FROM files")

    monkeypatch.setattr(main, "analyze_file", boom)
    _, job = upload("err.bin", b"x")
    assert (job["status"], job["analysis_error"]) == ("error", "Analysis failed")


def _analyze(tmp_path, job_id):
    p = tmp_path / "race.bin"
    p.write_bytes(os.urandom(20_000))
    with main.app.state.Session() as s:
        try:
            return analyzer.analyze_file(p, s, job_id, "race.bin")
        finally:
            forget_job(s, job_id)


def test_store_conflict_without_row_is_retried(client, tmp_path, monkeypatch):
    real, calls = analyzer._features, []

    def flaky(path, types):
        feats, ftype = real(path, types)
        if not calls:
            feats.embedded = [(999_999, 5)]  # FK violation that is NOT a duplicate file → re-select finds nothing
        calls.append(1)
        return feats, ftype

    monkeypatch.setattr(analyzer, "_features", flaky)
    assert _analyze(tmp_path, "d" * 32)["file"]["id"]
    assert len(calls) == 2


def test_store_conflict_gives_up_cleanly(client, tmp_path, monkeypatch):
    real = analyzer._features

    def always_bad(path, types):
        feats, ftype = real(path, types)
        feats.embedded = [(999_999, 5)]
        return feats, ftype

    monkeypatch.setattr(analyzer, "_features", always_bad)
    with pytest.raises(RuntimeError, match="concurrent"):
        _analyze(tmp_path, "e" * 32)


def test_file_deleted_before_name_insert_is_retried(client, tmp_path, monkeypatch):
    real, calls = analyzer._store_new_file, []

    def racing(session, feats, ftype):
        f = real(session, feats, ftype)
        if not calls:  # another job deletes the File row right now
            with main.app.state.Session() as other:
                other.execute(delete(File).where(File.id == f.id))
                other.commit()
        calls.append(1)
        return f

    monkeypatch.setattr(analyzer, "_store_new_file", racing)
    assert _analyze(tmp_path, "f" * 32)["file"]["id"]
    assert len(calls) == 2


# ── 7. Host header and Content-Length ────────────────────────────────────────
def test_unknown_host_rejected(client):
    assert client.get("/ping", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/ping", headers={"Host": "localhost:8000"}).status_code == 200


def test_allowed_hosts_parsing():
    assert main.ALLOWED_HOSTS == ["testserver", "localhost"]


def test_oversized_content_length_rejected_before_body(client, monkeypatch):
    def never(*_a):
        raise AssertionError("the endpoint must not run")

    monkeypatch.setattr(main, "MAX_CONTENT_LENGTH", 0)
    monkeypatch.setattr(main, "_reserve_slot", never)
    r = client.post("/upload", files={"file": ("big.bin", b"\0" * (1024 * 1024 + 10))})
    assert (r.status_code, r.json()) == (413, {"detail": "File too large"})


# ── 8. disk hygiene ──────────────────────────────────────────────────────────
def test_upload_cleans_up_when_job_creation_fails(client, monkeypatch):
    def broken(*_a):
        raise OSError("disk full")

    monkeypatch.setattr(main, "_write_json", broken)
    before, pending = _snapshot(), main._jobs_pending
    with pytest.raises(OSError):
        client.post("/upload", files={"file": ("x.bin", b"x" * 100)})
    assert _snapshot() == before
    assert main._jobs_pending == pending


def test_write_json_fsyncs(tmp_path, monkeypatch):
    synced = []
    real = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: synced.append(fd) or real(fd))
    main._write_json(tmp_path / "m.json", {"a": 1})
    assert synced and main._read_json(tmp_path / "m.json") == {"a": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["m.json"]


def test_purge_removes_orphans_and_survives_errors(client, monkeypatch):
    old = time.time() - 2 * main.ORPHAN_GRACE_S
    orphan_upload = main.UPLOAD_FOLDER / ("1" * 32 + "_gone.bin")
    orphan_archive = main.ARCHIVE_DIR / ("2" * 32)
    fresh_upload = main.UPLOAD_FOLDER / ("3" * 32 + "_in_flight.bin")  # job dir not created yet
    orphan_upload.write_bytes(b"x")
    orphan_archive.mkdir()
    (orphan_archive / "input.bin.gz").write_bytes(b"x")
    fresh_upload.write_bytes(b"x")
    for p in (orphan_upload, orphan_archive):
        os.utime(p, (old, old))

    jobs = []
    for c in "45":  # two expired jobs; deleting the first one blows up
        d = main.JOBS_DIR / (c * 32)
        d.mkdir()
        (d / "meta.json").write_text("{}")
        (main.UPLOAD_FOLDER / f"{c * 32}_file.bin").write_bytes(b"x")  # a real job has its upload
        os.utime(d, (old, old))
        jobs.append(d)
    real_delete = main.delete_job

    def flaky_delete(job_id):
        if job_id == "4" * 32:
            raise PermissionError(job_id)
        return real_delete(job_id)

    monkeypatch.setattr(main, "JOB_TTL_HOURS", 0.5)
    monkeypatch.setattr(main, "delete_job", flaky_delete)
    main.purge_old_jobs()
    assert not orphan_upload.exists() and not orphan_archive.exists()
    assert fresh_upload.exists()
    assert jobs[0].exists() and not jobs[1].exists()
    fresh_upload.unlink()
    real_delete("4" * 32)


def test_refresh_features_skips_damaged_meta(client, upload):
    data = os.urandom(30_000)
    bad, _ = upload("bad-meta.bin", data)
    good, _ = upload("good-meta.bin", data)  # same content → same File row, two names
    (main.JOBS_DIR / bad / "meta.json").write_text("{not json")
    with main.app.state.Session() as s:
        s.merge(Setting(key="features_version", value="0"))
        s.commit()
    main.refresh_outdated_features(main.app.state.Session)  # must not raise
    with main.app.state.Session() as s:
        assert s.get(Setting, "features_version").value != "0"
    main.delete_job(bad)
    main.delete_job(good)


# ── 9. API docs ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_docs_disabled_by_default(client, path):
    assert client.get(path).status_code == 404


# ── 10. graph ────────────────────────────────────────────────────────────────
def test_graph_names_capped(client, upload, graph):
    data = os.urandom(5_000)
    jobs = [upload(f"name-{i:02}.bin", data)[0] for i in range(23)]
    g, nodes, _ = graph(jobs[0])
    center = nodes[g["center"]]
    assert center["names_total"] == 23
    assert center["names"] == [f"name-{i:02}.bin" for i in range(20)]
    for j in jobs:
        main.delete_job(j)


# ── 11. TMPDIR in the data volume ────────────────────────────────────────────
def test_prepare_dirs_creates_tmpdir(tmp_path, monkeypatch):
    target = tmp_path / "data" / "tmp"
    monkeypatch.setenv("TMPDIR", str(target))
    monkeypatch.setattr(tempfile, "tempdir", "/somewhere/cached")  # restored after the test
    main.prepare_dirs()
    assert target.is_dir()
    assert tempfile.gettempdir() == str(target)


def test_raw_client_without_lifespan_still_checks_host():
    raw = TestClient(main.app, headers=CSRF, base_url="http://evil.example")
    assert raw.get("/ping").status_code == 400

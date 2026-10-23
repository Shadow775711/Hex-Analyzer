"""Bounded similarity cost, chunked uploads, zombie job directories and resumed jobs."""

import os
import random
import time

from sqlalchemy import func, select

import main
from conftest import wait_for_job
from models import FileName
from modules import features as F


def test_sketch_caps_stored_blocks(tmp_path):
    p = tmp_path / "big.bin"
    p.write_bytes(os.urandom(12 * 1024 * 1024))
    feats = F.extract_features(p, [])
    assert len(feats.block_hashes) == F.SKETCH_SIZE
    assert feats.block_total > F.SKETCH_SIZE


def test_bottom_k_estimate_is_close_to_exact():
    rnd = random.Random(7)
    common = {rnd.getrandbits(63) for _ in range(90_000)}
    a = common | {rnd.getrandbits(63) for _ in range(10_000)}
    b = common | {rnd.getrandbits(63) for _ in range(10_000)}
    assert abs(F.jaccard_bottom_k(a, b) - F.jaccard(a, b)) < 0.05


def test_bottom_k_exact_for_small_sets():
    assert F.jaccard_bottom_k({1, 2, 3}, {2, 3, 4}) == F.jaccard({1, 2, 3}, {2, 3, 4})


def test_large_near_identical_files_are_similar(client, upload, graph):
    """Files above the sketch size go through the bottom-k estimate."""
    data = os.urandom(6 * 1024 * 1024)
    ja, _ = upload("big-v1.bin", data)
    changed = bytearray(data)
    changed[3_000_000:3_000_100] = os.urandom(100)
    upload("big-v2.bin", b"PREFIX" + bytes(changed))
    _, nodes, rel = graph(ja)
    sim = rel("similar")
    assert sim and nodes[sim[0]["target"]]["label"] == "big-v2.bin"
    assert sim[0]["weight"] > 0.9


def test_upload_without_content_length_is_refused(client):
    body = iter([b'--x\r\nContent-Disposition: form-data; name="file"; filename="a"\r\n\r\nabc\r\n--x--\r\n'])
    r = client.post("/upload", content=body, headers={"content-type": "multipart/form-data; boundary=x"})
    assert r.status_code == 411


def test_job_dir_without_upload_is_swept(client):
    job_dir = main.JOBS_DIR / ("b" * 32)
    job_dir.mkdir()
    (job_dir / "meta.json").write_text('{"status": "done"}')
    old = time.time() - main.ORPHAN_GRACE_S - 10
    os.utime(job_dir, (old, old))
    main._purge_orphans()
    assert not job_dir.exists()


def test_unfinished_jobs_are_requeued_without_duplicate_entries(client, upload):
    job_id, _ = upload("resume.bin", os.urandom(20_000))
    meta_p = main.JOBS_DIR / job_id / "meta.json"
    meta = main._read_json(meta_p)
    meta.update(status="processing", analysis_ready=False)  # as if the server died mid-analysis
    main._write_json(meta_p, meta)

    main.requeue_unfinished(main.app.state.Session)
    job = wait_for_job(client, job_id)
    assert job["status"] == "done"
    with main.app.state.Session() as s:
        assert s.scalar(select(func.count()).select_from(FileName).where(FileName.job_id == job_id)) == 1


def test_unfinished_job_without_upload_is_marked_failed(client, upload):
    job_id, job = upload("gone.bin", os.urandom(5_000))
    (main.UPLOAD_FOLDER / job["stored_name"]).unlink()
    meta_p = main.JOBS_DIR / job_id / "meta.json"
    meta = main._read_json(meta_p)
    meta["status"] = "queued"
    main._write_json(meta_p, meta)

    main.requeue_unfinished(main.app.state.Session)
    assert main._read_json(meta_p)["status"] == "error"

"""Shared test setup: a separate data directory and an HTTP client with the CSRF header."""

import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

# DATA_DIR must be set BEFORE importing main (config is read at import time)
_DATA = tempfile.mkdtemp(prefix="hex-test-")
os.environ["DATA_DIR"] = _DATA
os.environ["ALLOWED_HOSTS"] = "testserver, localhost"  # TestClient sends Host: testserver
os.environ["MIN_FREE_MB"] = "1"  # don't fail on a nearly full CI disk; the 507 test lowers the bar itself
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

PNG = bytes.fromhex("89504E470D0A1A0A")
CSRF = {"X-Hex-Analyzer": "1"}


@pytest.fixture(scope="session")
def client():
    # `with` runs the lifespan (creates directories, the DB and the analysis executor)
    with TestClient(main.app, headers=CSRF) as c:
        yield c


@pytest.fixture
def upload(client):
    def _upload(name: str, data: bytes) -> tuple[str, dict]:
        r = client.post("/upload", files={"file": (name, data)})
        assert r.status_code == 202, r.text
        job_id = r.json()["job_id"]
        return job_id, wait_for_job(client, job_id)

    return _upload


def wait_for_job(client, job_id: str, timeout: float = 30) -> dict:
    """Analysis runs in the executor, not before the response — poll until it settles."""
    deadline = time.monotonic() + timeout
    while True:
        job = client.get(f"/jobs/{job_id}").json()
        if job.get("status") in ("done", "error"):
            return job
        assert time.monotonic() < deadline, f"job {job_id} stuck in {job.get('status')}"
        time.sleep(0.02)


@pytest.fixture
def graph(client):
    def _graph(job_id: str, **params) -> tuple[dict, dict, callable]:
        g = client.get(f"/jobs/{job_id}/graph", params=params).json()
        nodes = {n["id"]: n for n in g["nodes"]}

        def rel(name):
            return [e for e in g["edges"] if e["source"] == g["center"] and e["relation"] == name]

        return g, nodes, rel

    return _graph

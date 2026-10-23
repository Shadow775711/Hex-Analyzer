"""HTTP endpoints: upload, status, bytes, deletion, validation and CSRF protection."""

import os

import pytest
from fastapi.testclient import TestClient

import main
from conftest import PNG


def test_ping(client):
    assert client.get("/ping").json() == {"message": "API is working"}


def test_upload_and_result(client, upload):
    data = PNG + os.urandom(50_000)
    job_id, job = upload("../../etc/picture.png", data)
    assert job["filename"] == "picture.png"  # no directories in the name
    assert job["status"] == "done" and job["analysis_ready"]
    assert job["result"]["file"]["type"]["extension"] == "png"
    assert job["result"]["file"]["size"] == len(data)
    assert "hex_dump" not in job["result"]


def test_bytes_and_bounds(client, upload):
    data = os.urandom(10_000)
    job_id, _ = upload("b.bin", data)
    get = lambda **p: client.get(f"/jobs/{job_id}/bytes", params=p)  # noqa: E731
    assert get(offset=0, length=16).content == data[:16]
    assert get(offset=len(data) - 10, length=1000).content == data[-10:]
    assert get(offset=len(data) + 5).content == b""
    assert get(length=main.PAGE_MAX + 1).status_code == 422
    assert get(offset=-1).status_code == 422


@pytest.mark.parametrize("bad", ["garbage", "../../etc", "0" * 31, "Z" * 32])
def test_bad_job_id(client, bad):
    assert client.get(f"/jobs/{bad}").status_code in (404, 422)


def test_unknown_job_does_not_create_dir(client):
    unknown = "0" * 32
    assert client.get(f"/jobs/{unknown}").status_code == 404
    assert not (main.JOBS_DIR / unknown).exists()


def test_file_too_large(client, monkeypatch):
    monkeypatch.setattr(main, "MAX_CONTENT_LENGTH", 1000)
    before = set(main.UPLOAD_FOLDER.iterdir())
    r = client.post("/upload", files={"file": ("big.bin", b"\0" * 2000)})
    assert r.status_code == 413
    assert set(main.UPLOAD_FOLDER.iterdir()) == before  # nothing left on disk


def test_delete(client, upload):
    job_id, _ = upload("del.bin", os.urandom(1000))
    assert client.delete(f"/jobs/{job_id}").status_code == 204
    assert client.get(f"/jobs/{job_id}").status_code == 404
    assert client.delete(f"/jobs/{job_id}").status_code == 404


def test_csrf_without_header_rejected(client):
    raw = TestClient(main.app)  # without the default X-Hex-Analyzer header
    assert raw.post("/upload", files={"file": ("x.bin", b"x")}).status_code == 403
    assert raw.delete("/jobs/" + "0" * 32).status_code == 403
    assert raw.get("/ping").status_code == 200  # reads don't require the header


def test_cors_disabled_by_default(client):
    r = client.options(
        "/upload", headers={"Origin": "https://evil-site.example", "Access-Control-Request-Method": "POST"}
    )
    assert "access-control-allow-origin" not in r.headers


class TestTypes:
    def test_builtin_list(self, client):
        types = client.get("/types").json()
        assert len(types) >= 30 and all(t["builtin"] for t in types if t["extension"] == "png")

    def test_add_normalizes_hex_and_works_immediately(self, client, upload):
        r = client.post(
            "/types", json={"name": "My format", "extension": "MYF", "magic": "0x4D:59 46 21", "scan_inside": True}
        )
        assert r.status_code == 201
        t = r.json()
        assert (t["magic"], t["extension"], t["builtin"]) == ("4D594621", "myf", False)
        _, job = upload("x.myf", b"MYF!" + os.urandom(100))
        assert job["result"]["file"]["type"]["name"] == "My format"
        assert client.delete(f"/types/{t['id']}").status_code == 409  # assigned to a file

    @pytest.mark.parametrize("magic", ["XYZ", "ABC", "", "00" * 33])
    def test_bad_hex(self, client, magic):
        assert client.post("/types", json={"name": "x", "extension": "x", "magic": magic}).status_code == 422

    def test_short_signature_not_scanned_inside(self, client):
        r = client.post("/types", json={"name": "k", "extension": "k", "magic": "ABCD", "scan_inside": True})
        assert r.json()["scan_inside"] is False
        assert client.delete(f"/types/{r.json()['id']}").status_code == 204

    def test_builtin_cannot_be_deleted(self, client):
        builtin = next(t for t in client.get("/types").json() if t["builtin"])
        assert client.delete(f"/types/{builtin['id']}").status_code == 403

    def test_custom_signature_limit(self, client, monkeypatch):
        monkeypatch.setattr(main, "MAX_CUSTOM_TYPES", 0)
        r = client.post("/types", json={"name": "n", "extension": "n", "magic": "01020304"})
        assert r.status_code == 409

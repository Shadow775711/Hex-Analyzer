"""Maintenance: DELETE racing an analysis, orphaned entries, feature migration."""

import os
import shutil

from sqlalchemy import select

import main
from models import FileName, Setting


def _names(job_id):
    with main.app.state.Session() as s:
        return s.scalars(select(FileName).where(FileName.job_id == job_id)).all()


def test_delete_before_analysis_leaves_no_garbage(client, tmp_path):
    job_id = "a" * 32
    path = main.UPLOAD_FOLDER / f"{job_id}_x.bin"
    path.write_bytes(os.urandom(5000))
    # the job doesn't exist (as after DELETE) — the analysis must back out quietly
    main.run_analysis(job_id, path, main.app.state.Session, archive=False)
    assert _names(job_id) == []


def test_orphaned_entries_are_cleaned_up(client, upload):
    job_id, _ = upload("orphan.bin", os.urandom(3000))
    shutil.rmtree(main.JOBS_DIR / job_id)  # the job vanishes "from outside", the DB entry stays
    assert _names(job_id)
    main.forget_orphans(main.app.state.Session)
    assert _names(job_id) == []


def test_features_version_change_recomputes_files(client, upload):
    job_id, _ = upload("migration.bin", os.urandom(50_000))
    with main.app.state.Session() as s:
        s.merge(Setting(key="features_version", value="0"))
        s.commit()
    main.refresh_outdated_features(main.app.state.Session)
    with main.app.state.Session() as s:
        assert s.get(Setting, "features_version").value != "0"
    assert client.get(f"/jobs/{job_id}").json()["status"] == "done"

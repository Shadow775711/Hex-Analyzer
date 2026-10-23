"""File analysis: features (features.py) → type from the signature database → stored in the DB → result for the UI"""

from pathlib import Path

from sqlalchemy import delete, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import Embedded, File, FileBlock, FileName, FileType, Setting
from modules.features import FEATURES_VERSION, Features, ScanType, extract_features


class ConcurrentChange(Exception):
    """The DB changed under us (the same file stored or deleted by another job) — retry once."""


def detect_type(header: bytes, types: list[FileType]) -> FileType | None:
    """The longest matching signature wins (e.g. 'JPEG EXIF' over the generic 'JPEG')."""
    # sort by BYTE length — the stored HEX text may differ from 2 × bytes in legacy rows
    for t in sorted(types, key=lambda t: len(t.magic_bytes), reverse=True):
        magic = t.magic_bytes
        if magic and header[t.offset : t.offset + len(magic)] == magic:
            return t
    return None


def analyze_file(path: Path, session: Session, job_id: str, filename: str) -> dict:
    try:
        return _analyze_once(path, session, job_id, filename)
    except ConcurrentChange:
        session.rollback()
        try:
            return _analyze_once(path, session, job_id, filename)
        except ConcurrentChange:
            session.rollback()
            raise RuntimeError("Analysis gave up after a concurrent DB change") from None


def _analyze_once(path: Path, session: Session, job_id: str, filename: str) -> dict:
    types = {t.id: t for t in session.scalars(select(FileType))}
    feats, ftype = _features(path, types)

    file = session.scalar(select(File).where(File.sha256 == feats.sha256))
    if file is None:
        file = _store_new_file(session, feats, ftype)

    # a job re-queued after a restart may already have its entry — don't insert it twice
    if session.scalar(select(FileName).where(FileName.job_id == job_id)) is None:
        session.add(FileName(file_id=file.id, name=filename, job_id=job_id))
    try:
        session.commit()
    except IntegrityError as e:
        # the File row was deleted (last other upload of it removed) between select and insert
        raise ConcurrentChange from e

    return {
        "sha256": feats.sha256,
        "file": file.to_dict(),
        "entropy_profile": feats.entropy_profile,
        "profile_step": feats.profile_step,
        "embedded": [{"type": types[tid].to_dict(), "offset": off} for tid, off in feats.embedded],
    }


def _features(path: Path, types: dict[int, FileType]) -> tuple[Features, FileType | None]:
    scan = [ScanType(t.id, t.magic_bytes, t.offset, t.extension) for t in types.values() if t.scan_inside]
    feats = extract_features(path, scan)
    ftype = detect_type(feats.header, list(types.values()))

    # "ZIP contains ZIP" is noise: every archive entry starts with PK\x03\x04.
    # Drop hits of the same kind as the file itself — the extension counts only between built-in
    # types, otherwise a custom type named e.g. "zip" could hide real embedded files.
    if ftype:
        feats.embedded = [(t, o) for t, o in feats.embedded if not _same_kind(types[t], ftype)]
    return feats, ftype


def _same_kind(hit: FileType, ftype: FileType) -> bool:
    return hit.id == ftype.id or (hit.builtin and ftype.builtin and hit.extension == ftype.extension)


def features_outdated(session: Session) -> bool:
    row = session.get(Setting, "features_version")
    return row is None or row.value != str(FEATURES_VERSION)


def refresh_file(session: Session, file: File, path: Path) -> dict:
    """Recomputes blocks and hits of an existing file with the new algorithm; returns the new result fields."""
    types = {t.id: t for t in session.scalars(select(FileType))}
    feats, _ = _features(path, types)
    session.execute(delete(FileBlock).where(FileBlock.file_id == file.id))
    session.execute(delete(Embedded).where(Embedded.file_id == file.id))
    if feats.block_hashes:
        session.execute(insert(FileBlock), [{"file_id": file.id, "h": h} for h in feats.block_hashes])
    if feats.embedded:
        session.execute(insert(Embedded), [{"file_id": file.id, "type_id": t, "offset": o} for t, o in feats.embedded])
    file.block_count = feats.block_total
    session.commit()
    return {"embedded": [{"type": types[tid].to_dict(), "offset": off} for tid, off in feats.embedded]}


def mark_features_current(session: Session) -> None:
    session.merge(Setting(key="features_version", value=str(FEATURES_VERSION)))
    session.commit()


def _store_new_file(session: Session, feats: Features, ftype: FileType | None) -> File:
    file = File(
        sha256=feats.sha256,
        size=feats.size,
        entropy=feats.entropy,
        block_count=feats.block_total,
        type_id=ftype.id if ftype else None,
    )
    session.add(file)
    try:
        session.flush()  # assigns file.id
        if feats.block_hashes:
            session.execute(insert(FileBlock), [{"file_id": file.id, "h": h} for h in feats.block_hashes])
        if feats.embedded:
            session.execute(
                insert(Embedded), [{"file_id": file.id, "type_id": t, "offset": o} for t, o in feats.embedded]
            )
        session.commit()
    except IntegrityError as e:
        # Same file analysed concurrently — someone beat us to it, use their row.
        # None: it wasn't a duplicate (e.g. a type deleted meanwhile) or the row is gone again.
        session.rollback()
        file = session.scalar(select(File).where(File.sha256 == feats.sha256))
        if file is None:
            raise ConcurrentChange from e
        return file
    session.refresh(file)  # loads file.type and first_seen
    return file


def forget_job(session: Session, job_id: str) -> None:
    """Removes the upload from the DB; once a file has no uploads left, it goes too, along with its blocks."""
    name = session.scalar(select(FileName).where(FileName.job_id == job_id))
    if name is None:
        return
    file = name.file
    session.delete(name)
    session.flush()
    if not file.names:
        session.delete(file)  # file_blocks and embedded go via ON DELETE CASCADE
    session.commit()

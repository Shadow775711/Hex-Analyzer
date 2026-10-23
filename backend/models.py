"""Database model and session — plain SQLAlchemy 2.0.

file_types   — "how to recognise a PNG": known signatures (magic bytes + offset)
files        — "this particular file": one row per unique content (SHA-256)
file_names   — every upload: name + job_id (the same file can have many names)
file_blocks  — block hashes, for similarity (Jaccard)
embedded     — signatures found inside a file (the "contains" relation)
"""

import re
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    create_engine,
    delete,
    event,
    func,
    select,
    update,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker, validates

from modules.filetypes_seed import SEED_TYPES


class Base(DeclarativeBase):
    pass


def normalize_hex(text: str | None) -> str:
    """HEX without whitespace, ':' and '0x', upper case: '0x4d:5a' → '4D5A'."""
    if not text:
        return ""
    return re.sub(r"\s+", "", text).upper().replace("0X", "").replace(":", "")


def valid_magic(h: str) -> bool:
    """1–32 whole bytes of plain ASCII HEX (bytes.fromhex alone would also accept whitespace)."""
    return bool(re.fullmatch(r"[0-9A-F]{2,64}", h)) and len(h) % 2 == 0


def scannable(magic: bytes) -> bool:
    """Worth searching for inside files: ≥ 4 bytes and not one repeated byte (00000000 matches everywhere)."""
    return len(magic) >= 4 and magic.count(magic[0]) != len(magic)


class FileType(Base):
    __tablename__ = "file_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    extension: Mapped[str] = mapped_column(String(16))
    magic: Mapped[str] = mapped_column(String(64))  # HEX
    offset: Mapped[int] = mapped_column(Integer, default=0)
    scan_inside: Mapped[bool] = mapped_column(Boolean, default=False)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)  # from the seed list — cannot be deleted via the API

    @validates("magic")
    def _norm_magic(self, _key, value):
        return normalize_hex(value)

    @property
    def magic_bytes(self) -> bytes:
        # b"" for a legacy row that is still invalid (kept only because files reference it)
        return bytes.fromhex(self.magic) if valid_magic(self.magic) else b""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "extension": self.extension,
            "magic": self.magic,
            "offset": self.offset,
            "builtin": self.builtin,
        }


class File(Base):
    __tablename__ = "files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    size: Mapped[int] = mapped_column(BigInteger)
    entropy: Mapped[float] = mapped_column(Float)
    block_count: Mapped[int] = mapped_column(Integer)  # number of DISTINCT blocks (Jaccard denominator)
    type_id: Mapped[int | None] = mapped_column(ForeignKey("file_types.id"), index=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    type: Mapped[FileType | None] = relationship(lazy="joined")
    names: Mapped[list["FileName"]] = relationship(
        back_populates="file", cascade="all, delete-orphan", order_by="FileName.uploaded_at"
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "sha256": self.sha256,
            "size": self.size,
            "entropy": self.entropy,
            "type": self.type.to_dict() if self.type else None,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
        }


class FileName(Base):
    __tablename__ = "file_names"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    job_id: Mapped[str] = mapped_column(String(32), unique=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    file: Mapped[File] = relationship(back_populates="names")


class FileBlock(Base):
    __tablename__ = "file_blocks"

    file_id: Mapped[int] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), primary_key=True)
    h: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)


class Setting(Base):
    """Simple key → value (e.g. the features algorithm version, to know when to recompute)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))


class Embedded(Base):
    __tablename__ = "embedded"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), index=True)
    type_id: Mapped[int] = mapped_column(ForeignKey("file_types.id"))
    offset: Mapped[int] = mapped_column(BigInteger)


def make_session_factory(db_url: str) -> sessionmaker:
    """Creates the engine + tables, seeds the built-in signatures and returns a session factory."""
    # check_same_thread=False: analysis runs in a FastAPI pool thread
    # timeout=30: concurrent analyses wait for the write lock instead of failing at once with "database is locked"
    engine = create_engine(db_url, connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")  # reads don't wait for writes
        cur.execute("PRAGMA foreign_keys=ON")  # so that ON DELETE CASCADE works
        cur.close()

    Base.metadata.create_all(engine)
    builtin_added = _add_missing_columns(engine)
    Session = sessionmaker(engine, expire_on_commit=False)

    with Session() as s:
        if s.scalar(select(func.count()).select_from(FileType)) == 0:
            s.add_all(
                FileType(name=n, extension=e, magic=m, offset=o, scan_inside=sc, builtin=True)
                for n, e, m, o, sc in SEED_TYPES
            )
            s.commit()
        # fix for the wrong UF2 signature from the first database version
        s.execute(update(FileType).where(FileType.magic == "55463246").values(magic="5546320A"))
        _sanitize_types(s)
        if builtin_added:
            _promote_seed_rows(s)
        s.commit()
    return Session


def _sanitize_types(s) -> None:
    """Older versions stored whatever bytes.fromhex accepted (tabs, newlines, 1-byte scans) — clean that up."""
    referenced = set(s.scalars(select(File.type_id).where(File.type_id.is_not(None)).distinct()))
    for t in s.scalars(select(FileType)).all():
        t.magic = normalize_hex(t.magic)  # the validator normalises on assignment
        if valid_magic(t.magic):
            if t.scan_inside and not scannable(t.magic_bytes):
                t.scan_inside = False
        elif t.id in referenced:
            t.scan_inside = False  # files point at it — keep the row, but never search for it
        else:
            s.execute(delete(Embedded).where(Embedded.type_id == t.id))
            s.delete(t)


def _promote_seed_rows(s) -> None:
    """One-shot migration for databases predating the builtin column: mark the seeded rows.

    At most ONE row per seed entry and only an exact match — a user's copy of a seed signature
    must stay deletable and keep counting towards the custom-type limit."""
    for n, e, m, o, _ in SEED_TYPES:
        t = s.scalar(
            select(FileType)
            .where(FileType.name == n, FileType.extension == e, FileType.magic == m, FileType.offset == o)
            .where(FileType.builtin.is_(None) | ~FileType.builtin)
            .order_by(FileType.id)
            .limit(1)
        )
        if t is not None:
            t.builtin = True
            s.flush()  # so the next identical seed entry (if any) doesn't pick the same row


def _add_missing_columns(engine) -> bool:
    """create_all doesn't alter existing tables — add the columns introduced in newer versions.

    Returns True when the builtin column was just added (→ run the one-shot seed migration)."""
    with engine.begin() as conn:
        cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(file_types)")}
        if "builtin" not in cols:
            conn.exec_driver_sql("ALTER TABLE file_types ADD COLUMN builtin BOOLEAN DEFAULT 0")
            return True
    return False

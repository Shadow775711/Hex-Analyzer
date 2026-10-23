"""File features computed in ONE pass: SHA-256, entropy, block hashes, embedded signatures.

Similarity blocks are defined by CONTENT (content-defined chunking, CDC): a block boundary
falls where the hash of 8 consecutive bytes has 10 zero bits. After bytes are inserted
into the middle of a file, later boundaries land on the same spots in the content, so blocks
after the insertion still match — with fixed 4 KB blocks everything would shift.

Pure functions with no database — easy to check on their own, e.g.:
    >>> entropy_from_counts([100, 0, 0])
    0.0
    >>> entropy_from_counts([1, 1])
    1.0
    >>> jaccard({1, 2}, {2, 3})
    0.3333333333333333
"""

import hashlib
import heapq
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

FEATURES_VERSION = 3  # block/hit algorithm changed → the backend recomputes old files
BLOCK_SIZE = 4096  # entropy profile step (a multiple of it)
# Content-defined chunks: min / average / max. ~1.2 KB is a compromise measured on real files:
# larger chunks miss scattered small differences (ls↔dir: 10% at ~5 KB, 28% at ~1.2 KB),
# smaller ones add little and multiply DB rows (~80k per 100 MB).
CDC_MIN = 256
CDC_AVG_BITS = 10  # a cut candidate every ~2^10 bytes
CDC_MAX = 4096
SKETCH_SIZE = 2048  # block hashes stored per file (bottom-k sketch for similarity)
READ_SIZE = 1024 * 1024  # read 1 MB at a time (a multiple of BLOCK_SIZE)
HEADER_SIZE = 32774  # for type detection (ISO has 'CD001' at offset 32769)
MAX_HITS_PER_TYPE = 20  # more VALID hits of one type is just noise
# Raw candidates collected per type before validation: the cap must be well above
# MAX_HITS_PER_TYPE, or a few bare magic occurrences in front would hide a real embedded file.
MAX_RAW_HITS_PER_TYPE = 2000
PROFILE_POINTS = 512  # max number of entropy profile points


@dataclass
class ScanType:
    """A signature to search for inside a file."""

    id: int
    magic: bytes
    offset: int  # where magic sits relative to the start of the embedded file
    ext: str = ""  # validator key in VALIDATORS


@dataclass
class Features:
    sha256: str
    size: int
    header: bytes
    entropy: float
    entropy_profile: list[float]  # entropy of consecutive file segments
    profile_step: int  # bytes per profile point
    block_hashes: set[int] = field(default_factory=set)  # bottom-k sketch, at most SKETCH_SIZE
    block_total: int = 0  # distinct blocks before sketching
    embedded: list[tuple[int, int]] = field(default_factory=list)  # (type_id, offset)


def entropy_from_counts(counts) -> float:
    """Shannon entropy in bits per byte from a byte histogram.
    0 = all bytes identical, ~4-5 = text/code, ~8 = noise (encryption, compression)."""
    c = np.asarray(counts, dtype=np.float64)
    total = c.sum()
    if total == 0:
        return 0.0
    p = c[c > 0] / total
    return round(abs(float(-(p * np.log2(p)).sum())), 4)  # abs: no "-0.0"


def profile_step_for(size: int) -> int:
    """Profile segment size: a multiple of BLOCK_SIZE (a power of 2, so it divides READ_SIZE),
    chosen so there are at most PROFILE_POINTS points."""
    blocks = max(1, -(-size // BLOCK_SIZE))  # round up
    k = 1
    while blocks / k > PROFILE_POINTS:
        k *= 2
    return BLOCK_SIZE * k


def jaccard(a: set, b: set) -> float:
    """|A ∩ B| / |A ∪ B| — 1.0 = identical sets, 0.0 = nothing in common."""
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def jaccard_bottom_k(a: set[int], b: set[int], k: int | None = None) -> float:
    """Jaccard estimate from two bottom-k sketches: of the k smallest hashes of A ∪ B, the share
    found in both. Exact when |A ∪ B| ≤ k (files up to ~2.5 MB).

    >>> jaccard_bottom_k({1, 2, 3}, {2, 3, 4})
    0.5
    """
    k = k or SKETCH_SIZE
    union = heapq.nsmallest(k, a | b)
    if not union:
        return 0.0
    return sum(1 for h in union if h in a and h in b) / len(union)


def block_hash(block: bytes) -> int | None:
    """64-bit block hash; None for single-byte-value blocks (runs of zeros/0xFF are in every file)."""
    if block.count(block[0]) == len(block):
        return None
    # signed int64 — what SQLite fits in an INTEGER
    return int.from_bytes(hashlib.blake2b(block, digest_size=8).digest(), "big", signed=True)


# ── Content-defined chunks (CDC) ─────────────────────────────────────────────
_PRIME = np.uint64(0x9E3779B97F4A7C15)
_SALT = np.uint64(0x5BD1E9955BD1E995)  # so an all-zero window is not a candidate
_SHIFT = np.uint64(64 - CDC_AVG_BITS)


def cut_candidates(buf: bytes) -> np.ndarray:
    """Indices AFTER which a cut is allowed: the hash of the 8-byte window ending at i has CDC_AVG_BITS zero bits.

    >>> bool((cut_candidates(bytes(range(256)) * 64) >= 7).all())
    True
    """
    n = len(buf) - 7
    if n <= 0:
        return np.empty(0, dtype=np.int64)
    # the 8-byte window starting at i as a 64-bit number: instead of computing it,
    # read the memory 8 times at shift k and interleave (v[k], v[k+8], ...)
    v = np.empty(n, dtype=np.uint64)
    for k in range(8):
        v[k::8] = np.frombuffer(buf, dtype="<u8", count=(n - k + 7) // 8, offset=k)
    h = (v ^ _SALT) * _PRIME  # multiplication mod 2^64 mixes the bits
    return np.nonzero((h >> _SHIFT) == 0)[0] + 7


class Chunker:
    """Splits a stream into content-defined chunks; feed() returns completed chunks, finish() the last one."""

    def __init__(self) -> None:
        self.carry = b""  # bytes since the last cut (unfinished chunk)
        self.tail = b""  # ≤ 7 bytes BEFORE carry — needed for the hash window

    def feed(self, chunk: bytes) -> list[bytes]:
        buf = self.carry + chunk
        ext = self.tail + buf
        cuts = cut_candidates(ext) - len(self.tail) + 1
        blocks = []
        last = 0
        while True:
            i = int(np.searchsorted(cuts, last + CDC_MIN))
            nxt = int(cuts[i]) if i < len(cuts) else None
            if nxt is not None and nxt - last <= CDC_MAX:
                cut = nxt
            elif last + CDC_MAX <= len(buf):
                cut = last + CDC_MAX  # no candidate — forced cut
            else:
                break  # wait for more data
            blocks.append(buf[last:cut])
            last = cut
        self.tail = ext[: len(self.tail) + last][-7:]
        self.carry = buf[last:]
        return blocks

    def finish(self) -> list[bytes]:
        return [self.carry] if self.carry else []


# ── Validation of embedded hits ──────────────────────────────────────────────
# 4-byte signatures turn up by chance in compressed noise (e.g. CAFEBABE in a kernel).
# A real embedded file has a sensible header after the signature — check a few bytes.
# b = bytes from the start of the embedded file (≥ 32 if the file is long enough).
VALIDATORS = {
    "elf": lambda b: len(b) >= 7 and b[4] in (1, 2) and b[5] in (1, 2) and b[6] == 1,
    "class": lambda b: len(b) >= 8 and 45 <= int.from_bytes(b[6:8], "big") <= 80,
    "zip": lambda b: (
        len(b) >= 10
        and int.from_bytes(b[4:6], "little") <= 63
        and int.from_bytes(b[8:10], "little") in (0, 1, 6, 8, 9, 12, 14, 93, 95, 98, 99)
    ),
    "zst": lambda b: len(b) >= 5 and not b[4] & 0x08,  # reserved bit = 0
    "xz": lambda b: len(b) >= 8 and b[6] == 0 and b[7] < 0x10,
    "riff": lambda b: len(b) >= 12 and b[8:12] in (b"WAVE", b"AVI ", b"WEBP", b"ACON", b"RMID"),
    "ogg": lambda b: len(b) >= 5 and b[4] == 0,
    "flac": lambda b: len(b) >= 5 and b[4] & 0x7F == 0,  # first block: STREAMINFO
    "tif": lambda b: len(b) >= 8 and 8 <= int.from_bytes(b[4:8], "little" if b[0] == 0x49 else "big") < 1 << 31,
    "psd": lambda b: len(b) >= 6 and b[4:6] in (b"\x00\x01", b"\x00\x02"),
    "cab": lambda b: len(b) >= 8 and b[4:8] == b"\x00\x00\x00\x00",
    "mp4": lambda b: len(b) >= 12 and 8 <= int.from_bytes(b[0:4], "big") <= 512 and all(32 <= c < 127 for c in b[8:12]),
    "dex": lambda b: len(b) >= 8 and b[4:7].isdigit() and b[7] == 0,
    "wasm": lambda b: len(b) >= 8 and b[4:8] == b"\x01\x00\x00\x00",
    "uf2": lambda b: len(b) >= 8 and b[4:8] == bytes.fromhex("5751 5D9E"),
    "macho": lambda b: len(b) >= 8 and int.from_bytes(b[4:8], "little") in (7, 12, 0x01000007, 0x0100000C),
    "pdf": lambda b: len(b) >= 6 and 0x30 <= b[5] <= 0x39,
    "jpg": lambda b: len(b) >= 11 and b[6:11] in (b"JFIF\x00", b"Exif\x00"),
}


def validate_hits(path: Path, hits: dict[int, list[int]], types: list[ScanType]) -> list[tuple[int, int]]:
    """Keeps the first MAX_HITS_PER_TYPE hits per type that pass their format's validator (no validator → kept)."""
    by_id = {t.id: t for t in types}
    good = []
    with path.open("rb") as f:
        for tid, offsets in hits.items():
            check = VALIDATORS.get(by_id[tid].ext)
            kept = 0
            for off in offsets:
                if kept >= MAX_HITS_PER_TYPE:
                    break
                if check:
                    f.seek(off)
                    if not check(f.read(32)):
                        continue
                good.append((tid, off))
                kept += 1
    return sorted(good)


def find_embedded(buf: bytes, base: int, new_from: int, types: list[ScanType], hits: dict[int, list[int]]) -> None:
    """Searches buf for signatures; base = offset of buf in the file, new_from = index where the new bytes start.

    A hit counts only if it ends within the new bytes — that way the overlap
    (tail of the previous chunk) produces no duplicates.
    """
    for t in types:
        found = hits.setdefault(t.id, [])
        i = buf.find(t.magic)
        while i != -1 and len(found) < MAX_RAW_HITS_PER_TYPE:
            start = base + i - t.offset  # start of the embedded file
            if i + len(t.magic) > new_from and start > 0:
                found.append(start)
            i = buf.find(t.magic, i + 1)


def extract_features(path: Path, scan_types: list[ScanType]) -> Features:
    sha = hashlib.sha256()
    counts = np.zeros(256, dtype=np.int64)
    step = profile_step_for(path.stat().st_size)
    profile: list[float] = []
    blocks: set[int] = set()
    chunker = Chunker()
    hits: dict[int, list[int]] = {}
    header = b""
    size = 0

    overlap = max((len(t.magic) for t in scan_types), default=1) - 1
    tail = b""

    with path.open("rb") as f:
        while chunk := f.read(READ_SIZE):
            if len(header) < HEADER_SIZE:
                header += chunk[: HEADER_SIZE - len(header)]
            sha.update(chunk)
            arr = np.frombuffer(chunk, dtype=np.uint8)
            counts += np.bincount(arr, minlength=256)
            for i in range(0, len(arr), step):
                profile.append(entropy_from_counts(np.bincount(arr[i : i + step], minlength=256)))
            for block in chunker.feed(chunk):
                if (h := block_hash(block)) is not None:
                    blocks.add(h)

            buf = tail + chunk
            find_embedded(buf, size - len(tail), len(tail), scan_types, hits)
            tail = buf[-overlap:] if overlap else b""
            size += len(chunk)

    for block in chunker.finish():
        if (h := block_hash(block)) is not None:
            blocks.add(h)

    embedded = validate_hits(path, hits, scan_types)
    # Keep only the SKETCH_SIZE smallest hashes (bottom-k MinHash). Hashes are uniform, so this
    # is an unbiased sample that still estimates Jaccard well — and it caps the DB rows and the
    # graph query cost per file, even for crafted files cut into a block every 256 bytes.
    block_total = len(blocks)
    blocks = set(heapq.nsmallest(SKETCH_SIZE, blocks))

    return Features(
        sha256=sha.hexdigest(),
        size=size,
        header=header,
        entropy=entropy_from_counts(counts),
        entropy_profile=profile,
        profile_step=step,
        block_hashes=blocks,
        block_total=block_total,
        embedded=embedded,
    )

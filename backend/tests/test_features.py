"""Pure functions from modules/features.py — no database, no HTTP."""

import os

import numpy as np
import pytest

from modules import features as F


def test_entropy_edge_cases():
    assert F.entropy_from_counts([100, 0, 0]) == 0.0
    assert F.entropy_from_counts([1, 1]) == 1.0
    assert F.entropy_from_counts([0] * 256) == 0.0
    assert F.entropy_from_counts(np.bincount(np.frombuffer(os.urandom(1 << 16), np.uint8), minlength=256)) > 7.9


def test_jaccard():
    assert F.jaccard({1, 2}, {2, 3}) == pytest.approx(1 / 3)
    assert F.jaccard(set(), set()) == 0.0
    assert F.jaccard({1}, {1}) == 1.0


def test_single_byte_block_is_skipped():
    assert F.block_hash(b"\0" * 4096) is None
    assert F.block_hash(b"\xff" * 10) is None
    assert isinstance(F.block_hash(b"ab"), int)


def _chunks(data: bytes, step: int) -> list[bytes]:
    c = F.Chunker()
    out = []
    for i in range(0, len(data), step):
        out += c.feed(data[i : i + step])
    return out + c.finish()


def test_chunker_independent_of_stream_split_and_lossless():
    data = os.urandom(2_000_000)
    a, b = _chunks(data, 1 << 20), _chunks(data, 77_777)
    assert a == b
    assert b"".join(a) == data
    assert all(len(x) <= F.CDC_MAX for x in a)
    assert all(len(x) >= F.CDC_MIN for x in a[:-1])


def test_chunker_resilient_to_insertion():
    """After inserting bytes at the start, almost all chunks stay the same."""
    data = os.urandom(500_000)
    hashes = lambda d: {F.block_hash(b) for b in _chunks(d, 1 << 20)}  # noqa: E731
    assert F.jaccard(hashes(data), hashes(b"X" * 100 + data)) > 0.95


@pytest.mark.parametrize(
    ("ext", "good", "bad"),
    [
        ("elf", bytes.fromhex("7F454C46020101") + b"\0" * 9, bytes.fromhex("7F454C46090909") + b"\0" * 9),
        ("class", bytes.fromhex("CAFEBABE00000041"), bytes.fromhex("CAFEBABE0000FFFF")),
        ("zip", bytes.fromhex("504B0304140000000800"), bytes.fromhex("504B0304FF0000007700")),
        ("riff", b"RIFF\0\0\0\0WEBP", b"RIFF\0\0\0\0ABCD"),
    ],
)
def test_header_validators(ext, good, bad):
    assert F.VALIDATORS[ext](good)
    assert not F.VALIDATORS[ext](bad)


def test_embedded_only_with_valid_header(tmp_path):
    blob = bytearray(os.urandom(300_000))
    blob[10_000:10_010] = bytes.fromhex("504B0304140000000800")  # real ZIP
    blob[50_000:50_004] = bytes.fromhex("CAFEBABE")  # magic alone — noise
    blob[50_006:50_008] = b"\xff\xff"
    p = tmp_path / "blob.bin"
    p.write_bytes(bytes(blob))
    types = [F.ScanType(1, bytes.fromhex("504B0304"), 0, "zip"), F.ScanType(2, bytes.fromhex("CAFEBABE"), 0, "class")]
    assert F.extract_features(p, types).embedded == [(1, 10_000)]


def test_embedded_across_read_boundary(tmp_path):
    blob = bytearray(os.urandom(F.READ_SIZE * 2))
    blob[F.READ_SIZE - 3 : F.READ_SIZE + 5] = bytes.fromhex("89504E470D0A1A0A")  # PNG split by the 1 MB boundary
    p = tmp_path / "b.bin"
    p.write_bytes(bytes(blob))
    feats = F.extract_features(p, [F.ScanType(7, bytes.fromhex("89504E470D0A1A0A"), 0, "png")])
    assert feats.embedded == [(7, F.READ_SIZE - 3)]


def test_entropy_profile_has_at_most_512_points(tmp_path):
    p = tmp_path / "zeros.bin"
    p.write_bytes(b"\0" * 5_000_000)
    feats = F.extract_features(p, [])
    assert len(feats.entropy_profile) <= F.PROFILE_POINTS
    assert max(feats.entropy_profile) == 0.0
    assert feats.block_hashes == set()

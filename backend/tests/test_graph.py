"""Relations between files and the graph (/jobs/{id}/graph)."""

import io
import os
import zipfile

from conftest import PNG


def test_similar_identical_and_type(client, upload, graph):
    base = PNG + os.urandom(400_000)
    v2 = bytearray(base)
    v2[200_000:200_050] = os.urandom(50)
    ja, _ = upload("photo.png", base)
    upload("photo_v2.png", bytes(v2))
    upload("copy.png", base)  # identical → same node
    upload("other.png", PNG + os.urandom(30_000))

    g, nodes, rel = graph(ja)
    sim = rel("similar")
    assert [nodes[e["target"]]["label"] for e in sim] == ["photo_v2.png"]
    assert sim[0]["weight"] > 0.9
    assert {"photo.png", "copy.png"} <= set(nodes[g["center"]]["names"])
    assert any(n["label"] == "other.png" for n in nodes.values())  # same type
    assert all(  # every file pinned to its type
        any(e["source"] == n["id"] and e["relation"] == "is_type" for e in g["edges"])
        for n in nodes.values()
        if n["kind"] == "file"
    )
    _, _, rel_strict = graph(ja, min_similarity=1.0)
    assert not rel_strict("similar")


def test_insertion_keeps_similarity(upload, graph):
    data = os.urandom(300_000)
    ja, _ = upload("program", data)
    upload("program_with_insertion", data[:1000] + b"A" * 100 + data[1000:])
    _, _, rel = graph(ja)
    assert rel("similar") and rel("similar")[0]["weight"] > 0.9


def test_contains_and_no_zip_noise(upload, graph):
    blob = bytearray(os.urandom(300_000))
    blob[10_000:10_010] = bytes.fromhex("504B0304140000000800")
    blob[150_000:150_007] = bytes.fromhex("7F454C46020101")
    jk, res = upload("container.bin", bytes(blob))
    assert res["result"]["file"]["type"] is None
    assert sorted((e["type"]["extension"], e["offset"]) for e in res["result"]["embedded"]) == [
        ("elf", 150_000),
        ("zip", 10_000),
    ]
    _, nodes, rel = graph(jk)
    assert sorted(nodes[e["target"]]["extension"] for e in rel("contains")) == ["elf", "zip"]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i in range(5):
            z.writestr(f"file{i}.txt", os.urandom(1000))
    _, rz = upload("archive.zip", buf.getvalue())
    assert rz["result"]["file"]["type"]["extension"] == "zip"
    assert rz["result"]["embedded"] == []  # "ZIP contains ZIP" filtered out


def test_same_name(upload, graph):
    upload("firmware-sec.bin", os.urandom(20_000))
    j2, _ = upload("firmware-sec.bin", os.urandom(20_000))
    _, _, rel = graph(j2)
    assert len(rel("same_name")) == 1


def test_deleted_disappears_from_graph(client, upload, graph):
    base = os.urandom(200_000)
    ja, _ = upload("a.bin", base)
    jb, _ = upload("b.bin", base[:-100] + os.urandom(100))
    assert graph(ja)[2]("similar")
    client.delete(f"/jobs/{jb}")
    assert not graph(ja)[2]("similar")
    assert client.get(f"/jobs/{jb}/graph").status_code == 404

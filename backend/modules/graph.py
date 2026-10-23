"""Relations graph around a single file — computed live, so files uploaded later show up too.

Nodes:     file, type (a type from the signature database)
Relations: is_type   file → its type (files of the same type cluster around the type node)
           similar   shared content-defined chunks (Jaccard), weight 0–1
           contains  a signature of another type sits inside the file (offset)
           same_name same name, different content (e.g. successive firmware versions)
Identical files (same SHA-256) are ONE node with a list of names — see `names` (first 20) and `names_total`.
"""

from collections.abc import Callable

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from models import Embedded, File, FileBlock, FileName, FileType
from modules.features import jaccard_bottom_k

MAX_NAMES_PER_NODE = 20  # a file uploaded under thousands of names would bloat every graph response

SIMILAR_SQL = text(
    """
    SELECT b2.file_id, COUNT(*) AS shared
    FROM file_blocks b1
    JOIN file_blocks b2 ON b2.h = b1.h AND b2.file_id != b1.file_id
    WHERE b1.file_id = :fid
    GROUP BY b2.file_id
    ORDER BY shared DESC
    LIMIT :candidates
    """
)
SIMILAR_CANDIDATES = 200  # most-overlapping files scored per graph request (bounds the cost)


def build_graph(
    session: Session,
    file_id: int,
    job_exists: Callable[[str], bool],
    min_similarity: float = 0.05,
    limit: int = 25,
) -> dict:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def add_type(t: FileType) -> str:
        nid = f"t:{t.id}"
        nodes.setdefault(nid, {**t.to_dict(), "id": nid, "type_id": t.id, "kind": "type", "label": t.name})
        return nid

    def add_file(f: File, current: bool = False) -> str:
        nid = f"f:{f.id}"
        if nid in nodes:
            return nid
        uploads = [{"name": n.name, "job_id": n.job_id, "uploaded_at": n.uploaded_at.isoformat()} for n in f.names]
        live = [u for u in uploads if job_exists(u["job_id"])]
        names = sorted({u["name"] for u in uploads})
        nodes[nid] = {
            "id": nid,
            "file_id": f.id,
            "kind": "file",
            "current": current,
            "label": uploads[-1]["name"] if uploads else f.sha256[:12],
            "names": names[:MAX_NAMES_PER_NODE],
            "names_total": len(names),
            "job_id": live[-1]["job_id"] if live else None,  # for "open this file"
            **{k: v for k, v in f.to_dict().items() if k != "id"},
        }
        # every file is pinned to its type → files form clusters
        if f.type:
            edges.append({"source": nid, "target": add_type(f.type), "relation": "is_type"})
        return nid

    center = session.get(File, file_id)
    if center is None:
        return {"center": None, "nodes": [], "edges": []}
    cid = add_file(center, current=True)

    # ── similar: shared blocks → Jaccard = shared / (A + B − shared)
    shared = dict(session.execute(SIMILAR_SQL, {"fid": file_id, "candidates": SIMILAR_CANDIDATES}).all())
    if shared:
        # each file stores a bottom-k sketch of its blocks — estimate Jaccard from the sketches
        sketches: dict[int, set[int]] = {fid: set() for fid in [file_id, *shared]}
        for fid, h in session.execute(select(FileBlock.file_id, FileBlock.h).where(FileBlock.file_id.in_(sketches))):
            sketches[fid].add(h)
        others = session.scalars(select(File).where(File.id.in_(shared))).all()
        scored = []
        for f in others:
            sim = jaccard_bottom_k(sketches[file_id], sketches[f.id])
            if sim >= min_similarity:
                scored.append((sim, f))
        for sim, f in sorted(scored, key=lambda x: x[0], reverse=True)[:limit]:
            edges.append(
                {
                    "source": cid,
                    "target": add_file(f),
                    "relation": "similar",
                    "weight": round(sim, 4),
                    "label": f"{sim:.0%}",
                }
            )

    # ── contains: signatures found inside the file
    rows = session.execute(
        select(Embedded.type_id, func.count(), func.min(Embedded.offset))
        .where(Embedded.file_id == file_id)
        .group_by(Embedded.type_id)
    ).all()
    for type_id, count, first in rows:
        edges.append(
            {
                "source": cid,
                "target": add_type(session.get(FileType, type_id)),
                "relation": "contains",
                "count": count,
                "label": f"{count}× from 0x{first:X}",
            }
        )

    # ── same name, different content
    names = {n.name for n in center.names}
    same_name = session.scalars(
        select(File).join(FileName).where(FileName.name.in_(names), File.id != file_id).distinct().limit(limit)
    ).all()
    for f in same_name:
        edges.append({"source": cid, "target": add_file(f), "relation": "same_name"})

    # ── same type: newest files (they attach to the type node via is_type)
    if center.type_id is not None:
        same_type = session.scalars(
            select(File)
            .where(File.type_id == center.type_id, File.id != file_id)
            .order_by(File.first_seen.desc(), File.id.desc())
            .limit(limit)
        ).all()
        for f in same_type:
            add_file(f)

    return {"center": cid, "nodes": list(nodes.values()), "edges": edges}

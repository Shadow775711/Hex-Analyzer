// src/components/graph/GraphView.jsx
// Relation graph from the backend (/jobs/{id}/graph): files (circles) and types (squares).
import React, { useEffect, useMemo, useRef, useState } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { forceCollide } from 'd3-force';
import useElementSize from '../../hooks/useElementSize';
import { cappedNames, displayName, formatBytes, hex, truncate } from '../../lib/format';
import { RELATIONS } from './relations';

const NODE = {
  current: '#3b93eb',
  file: '#9ca3af',
  type: '#7c3aed',
  text: '#e6e6e6',
};

const HEIGHT = 560;

export default function GraphView({ graph, currentJobId, onOpenJob }) {
  const { ref: sizeRef, width } = useElementSize();
  const fgRef = useRef(null);
  const [enabled, setEnabled] = useState({ similar: true, contains: true, same_name: true, is_type: true });
  const [minSim, setMinSim] = useState(0.1);
  const [hover, setHover] = useState(null);
  // the selection is stored together with the graph it belongs to — new graph = no selection
  // (no effect that would reset it and force a second render)
  const [selection, setSelection] = useState(null);
  const selected = selection?.graph === graph ? selection.node : null;
  const setSelected = (node) => setSelection(node ? { graph, node } : null);

  // Nodes as stable objects — the graph engine keeps x/y positions in them
  const nodeById = useMemo(() => {
    const m = new Map();
    (graph?.nodes ?? []).forEach((n) => n && m.set(n.id, { ...n }));
    return m;
  }, [graph]);

  // Filtering: center + whatever connects to it via a visible relation (+ type cluster)
  const data = useMemo(() => {
    const center = graph?.center;
    if (!center) return { nodes: [], links: [] };
    const raw = graph.edges ?? [];
    const passes = (e) => enabled[e.relation] && (e.relation !== 'similar' || (e.weight ?? 0) >= minSim);

    const visible = new Set([center]);
    raw.forEach((e) => {
      if (e.source === center && e.relation !== 'is_type' && passes(e)) visible.add(e.target);
    });
    if (enabled.is_type) {
      const centerType = raw.find((e) => e.source === center && e.relation === 'is_type')?.target;
      if (centerType) {
        visible.add(centerType);
        raw.forEach((e) => e.relation === 'is_type' && e.target === centerType && visible.add(e.source));
      }
      // types of visible files are shown too — they give context
      raw.forEach((e) => e.relation === 'is_type' && visible.has(e.source) && visible.add(e.target));
    }

    return {
      nodes: [...visible].map((id) => nodeById.get(id)).filter(Boolean),
      // edge copies: the engine replaces source/target with objects
      links: raw
        .filter((e) => passes(e) && visible.has(e.source) && visible.has(e.target))
        .map((e) => ({ ...e })),
    };
  }, [graph, nodeById, enabled, minSim]);

  const neighbors = useMemo(() => {
    const m = new Map();
    data.links.forEach((l) => {
      const s = l.source.id ?? l.source;
      const t = l.target.id ?? l.target;
      if (!m.has(s)) m.set(s, new Set());
      if (!m.has(t)) m.set(t, new Set());
      m.get(s).add(t);
      m.get(t).add(s);
    });
    return m;
  }, [data]);

  // the canvas is mounted only once the container width is known — the effects below must
  // re-run then, otherwise data arriving earlier leaves the graph with weak default forces
  const ready = width > 0;

  // forces: shorter edges for strong similarity, repulsion, no overlapping
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;
    fg.d3Force('link')?.distance((l) =>
      l.relation === 'is_type' ? 70 : l.relation === 'similar' ? 160 - 100 * (l.weight ?? 0) : 120
    );
    fg.d3Force('charge')?.strength(-260);
    fg.d3Force('collide', forceCollide().radius(22));
    fg.d3ReheatSimulation();
  }, [data, ready]);

  useEffect(() => {
    const t = setTimeout(() => fgRef.current?.zoomToFit(400, 70), 600);
    return () => clearTimeout(t);
  }, [graph, ready]);

  useEffect(() => {
    if (!selected) return;
    const onKey = (e) => e.key === 'Escape' && setSelection(null);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [selected]);

  const dimmed = (id) => hover && hover.id !== id && !neighbors.get(hover.id)?.has(id);

  const drawNode = (node, ctx, scale) => {
    ctx.globalAlpha = dimmed(node.id) ? 0.25 : 1;
    if (node.kind === 'type') {
      const s = 9;
      ctx.fillStyle = NODE.type;
      ctx.beginPath();
      ctx.roundRect(node.x - s, node.y - s, 2 * s, 2 * s, 3);
      ctx.fill();
    } else {
      const r = node.current ? 10 : 7;
      ctx.fillStyle = node.current ? NODE.current : NODE.file;
      ctx.beginPath();
      ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
      ctx.fill();
      if (node.current) {
        ctx.strokeStyle = '#fff';
        ctx.lineWidth = 2 / scale;
        ctx.stroke();
      }
    }
    if (selected?.id === node.id) {
      ctx.strokeStyle = '#fbbf24';
      ctx.lineWidth = 3 / scale;
      ctx.beginPath();
      ctx.arc(node.x, node.y, 14, 0, 2 * Math.PI);
      ctx.stroke();
    }
    // labels at a fixed on-screen size (12 px), regardless of zoom
    const fontSize = 12 / scale;
    ctx.font = `${node.current ? 'bold ' : ''}${fontSize}px ui-monospace, monospace`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillStyle = NODE.text;
    // Array.from inside truncate: code points, so a surrogate pair (emoji) is never cut in half
    const label = truncate(displayName(node.label), 28);
    ctx.fillText(label, node.x, node.y + 12 + 2 / scale);
    ctx.globalAlpha = 1;
  };

  // edge labels: similarity %, “2× from 0x…”
  const drawLinkLabel = (link, ctx, scale) => {
    if (!link.label) return;
    const x = (link.source.x + link.target.x) / 2;
    const y = (link.source.y + link.target.y) / 2;
    const fontSize = 11 / scale;
    ctx.font = `bold ${fontSize}px ui-monospace, monospace`;
    // dark “pill” under the label — readable even over crossing lines
    const w = ctx.measureText(link.label).width + 8 / scale;
    const h = fontSize + 4 / scale;
    ctx.fillStyle = 'rgba(20,20,20,0.9)';
    ctx.beginPath();
    ctx.roundRect(x - w / 2, y - h / 2, w, h, 3 / scale);
    ctx.fill();
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = RELATIONS[link.relation]?.color ?? NODE.text;
    ctx.fillText(link.label, x, y);
  };

  const counts = useMemo(() => {
    const c = {};
    (graph?.edges ?? []).forEach((e) => {
      if (e.source === graph.center) c[e.relation] = (c[e.relation] ?? 0) + 1;
    });
    return c;
  }, [graph]);

  if (!graph) return <div className="muted graph-empty">Loading graph…</div>;

  return (
    <div className="graph">
      <div className="graph-toolbar">
        {Object.entries(RELATIONS).map(([key, r]) => (
          <label key={key} className="graph-toggle" style={{ '--c': r.color }}>
            <input
              type="checkbox"
              checked={enabled[key]}
              onChange={(e) => setEnabled((p) => ({ ...p, [key]: e.target.checked }))}
            />
            <span className="graph-swatch" />
            {r.label}
            {key !== 'is_type' && <span className="muted"> ({counts[key] ?? 0})</span>}
          </label>
        ))}

        <label className="graph-slider" title="Show only files at least this similar">
          Similarity ≥ {Math.round(minSim * 100)}%
          <input
            type="range"
            min={0.05}
            max={1}
            step={0.05}
            value={minSim}
            disabled={!enabled.similar}
            onChange={(e) => setMinSim(Number(e.target.value))}
          />
        </label>

        <span className="graph-spacer" />
        <button className="btn btn--sm" onClick={() => fgRef.current?.zoomToFit(400, 70)}>
          Fit
        </button>
        <button className="btn btn--sm" onClick={() => fgRef.current?.zoom(fgRef.current.zoom() * 1.3, 300)}>
          ＋
        </button>
        <button className="btn btn--sm" onClick={() => fgRef.current?.zoom(fgRef.current.zoom() / 1.3, 300)}>
          －
        </button>
      </div>

      <div className="graph-legend muted small">
        <span>
          <i className="dot" style={{ background: NODE.current }} /> this file
        </span>
        <span>
          <i className="dot" style={{ background: NODE.file }} /> other files
        </span>
        <span>
          <i className="sq" style={{ background: NODE.type }} /> file type
        </span>
        <span>Click a node to see details.</span>
      </div>

      <div ref={sizeRef} className="graph-canvas" style={{ height: HEIGHT }}>
        {width > 0 && (
          <ForceGraph2D
            ref={fgRef}
            width={width}
            height={HEIGHT}
            graphData={data}
            backgroundColor="rgba(0,0,0,0)"
            cooldownTicks={150}
            // with only a few nodes "fit" would zoom in so far that nodes become huge
            maxZoom={3}
            nodeCanvasObject={drawNode}
            nodePointerAreaPaint={(node, color, ctx) => {
              ctx.fillStyle = color;
              ctx.beginPath();
              ctx.arc(node.x, node.y, 14, 0, 2 * Math.PI);
              ctx.fill();
            }}
            // no hover tooltips: force-graph defaults linkLabel to the 'name' field and renders
            // string tooltips with innerHTML — empty accessors keep server data out of that sink
            nodeLabel={() => ''}
            linkLabel={() => ''}
            onNodeHover={setHover}
            onNodeClick={setSelected}
            onBackgroundClick={() => setSelected(null)}
            linkColor={(l) => RELATIONS[l.relation]?.color}
            linkWidth={(l) =>
              l.relation === 'similar' ? 1 + 4 * (l.weight ?? 0) : l.relation === 'is_type' ? 1 : 1.5
            }
            linkLineDash={(l) => RELATIONS[l.relation]?.dash}
            linkDirectionalArrowLength={(l) => (l.relation === 'contains' ? 5 : 0)}
            linkDirectionalArrowRelPos={0.9}
            linkCanvasObjectMode={() => 'after'}
            linkCanvasObject={drawLinkLabel}
          />
        )}

        {data.nodes.length <= 1 && (
          <div className="graph-overlay muted">
            No relations yet — upload more files and they will appear here.
          </div>
        )}

        {selected && (
          <NodePanel
            node={selected}
            currentJobId={currentJobId}
            onOpenJob={onOpenJob}
            onClose={() => setSelected(null)}
          />
        )}
      </div>
    </div>
  );
}

function NodePanel({ node, currentJobId, onOpenJob, onClose }) {
  const canOpen = node.kind === 'file' && node.job_id && node.job_id !== currentJobId;
  return (
    <aside className="graph-panel">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <strong className="mono">{displayName(node.label)}</strong>
        <button className="btn btn--sm" onClick={onClose} title="Close (Esc)">
          ✕
        </button>
      </div>

      {node.kind === 'type' ? (
        <dl className="kv">
          <dt>Kind</dt>
          <dd>file type (signature)</dd>
          <dt>Extension</dt>
          <dd>.{displayName(node.extension)}</dd>
          <dt>Magic</dt>
          <dd className="mono">{node.magic}</dd>
          <dt>Offset</dt>
          <dd className="mono">{hex(node.offset)}</dd>
        </dl>
      ) : (
        <dl className="kv">
          <dt>Names</dt>
          <dd>
            <NamesList node={node} />
          </dd>
          <dt>Type</dt>
          <dd>{node.type?.name != null ? displayName(node.type.name) : 'unknown'}</dd>
          <dt>Size</dt>
          <dd>{formatBytes(node.size)}</dd>
          <dt>Entropy</dt>
          <dd>{node.entropy?.toFixed(2)} bit/B</dd>
          <dt>SHA-256</dt>
          <dd className="mono small">{node.sha256}</dd>
          <dt>First seen</dt>
          <dd>{node.first_seen?.replace('T', ' ').slice(0, 19)}</dd>
        </dl>
      )}

      {node.kind === 'file' && (
        <div className="row">
          {canOpen && (
            <button className="btn btn--primary" onClick={() => onOpenJob(node.job_id)}>
              Open this file
            </button>
          )}
          {!node.job_id && <span className="muted small">The file is no longer available for preview.</span>}
          <button className="btn" onClick={() => navigator.clipboard?.writeText(node.sha256)}>
            ⧉ SHA
          </button>
        </div>
      )}
    </aside>
  );
}

/** Names of a file — the backend sends at most 20 of them plus names_total */
function NamesList({ node }) {
  const { shown, more } = cappedNames(node);
  if (!shown.length && !more) return '—';
  return (
    <>
      {shown.map(displayName).join(', ')}
      {more > 0 && (
        <span className="muted">
          {shown.length ? ' ' : ''}+{more} more
        </span>
      )}
    </>
  );
}

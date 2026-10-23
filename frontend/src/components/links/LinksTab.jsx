// src/components/links/LinksTab.jsx — relations as a list, grouped by relation
import React from 'react';
import { RELATIONS } from '../graph/relations';
import { cappedNames, displayName, formatBytes } from '../../lib/format';

export default function LinksTab({ graph, currentJobId, onOpenJob }) {
  if (!graph) return <div className="muted">Loading relations…</div>;

  const edges = graph.edges ?? [];
  const nodes = new Map((graph.nodes ?? []).map((n) => [n?.id, n]));
  // edges only to nodes that exist — a malformed response must not crash the list
  const fromCenter = (rel) =>
    edges.filter((e) => e.source === graph.center && e.relation === rel && nodes.get(e.target));
  const center = nodes.get(graph.center);
  const centerType = fromCenter('is_type')[0]?.target;
  const sameType = edges
    .filter((e) => e.relation === 'is_type' && e.target === centerType && e.source !== graph.center)
    .map((e) => nodes.get(e.source))
    .filter(Boolean);
  const centerNames = cappedNames(center);

  const similar = fromCenter('similar');
  const contains = fromCenter('contains');
  const sameName = fromCenter('same_name');

  const fileRow = (n, extra) => {
    // backend sends at most 20 names + names_total
    const { shown, more } = cappedNames(n);
    const others = shown.filter((x) => x !== n.label).map(displayName);
    if (more > 0) others.push(`+${more} more`);
    return (
      <li key={n.id} className="link-row">
        <div className="stack stack--tight" style={{ minWidth: 0 }}>
          <strong className="ellipsis">{displayName(n.label)}</strong>
          <span className="muted small">
            {n.type?.name != null ? displayName(n.type.name) : 'unknown type'} · {formatBytes(n.size)}
            {shown.length + more > 1 && others.length > 0 && ` · also as: ${others.join(', ')}`}
          </span>
        </div>
        {extra ?? <span />}
        {n.job_id && n.job_id !== currentJobId ? (
          <button className="btn btn--sm" onClick={() => onOpenJob(n.job_id)}>
            Open
          </button>
        ) : (
          <span />
        )}
      </li>
    );
  };

  const nothing =
    !similar.length &&
    !contains.length &&
    !sameName.length &&
    !sameType.length &&
    centerNames.shown.length + centerNames.more < 2;

  return (
    <div className="stack">
      {nothing && (
        <div className="alert alert--info">
          No relations yet — upload more files and they will appear here.
        </div>
      )}

      {centerNames.shown.length + centerNames.more > 1 && (
        <Group title="Identical (same SHA-256)" color="#3b93eb">
          <p className="small" style={{ margin: 0 }}>
            The same file was uploaded under the names:{' '}
            {centerNames.shown.map((n) => (
              <code key={n} style={{ marginRight: 6 }}>
                {displayName(n)}
              </code>
            ))}
            {centerNames.more > 0 && <span className="muted">+{centerNames.more} more</span>}
          </p>
        </Group>
      )}

      {similar.length > 0 && (
        <Group
          title={RELATIONS.similar.label}
          color={RELATIONS.similar.color}
          hint="shared content fragments — versions, patches, insertions"
        >
          <ul className="link-list">
            {similar.map((e) =>
              fileRow(
                nodes.get(e.target),
                <div className="sim" title={`${(e.weight * 100).toFixed(1)}% shared blocks`}>
                  <div className="sim-bar" style={{ width: `${e.weight * 100}%` }} />
                  <span>{e.label}</span>
                </div>
              )
            )}
          </ul>
        </Group>
      )}

      {contains.length > 0 && (
        <Group
          title={RELATIONS.contains.label}
          color={RELATIONS.contains.color}
          hint="signatures of other types inside the file — details and jump to HEX in the “File” tab"
        >
          <ul className="link-list">
            {contains.map((e) => {
              const t = nodes.get(e.target);
              return (
                <li key={e.target} className="link-row">
                  <strong>{displayName(t?.label)}</strong>
                  <span className="mono small">{e.label}</span>
                  <span />
                </li>
              );
            })}
          </ul>
        </Group>
      )}

      {sameName.length > 0 && (
        <Group
          title={RELATIONS.same_name.label}
          color={RELATIONS.same_name.color}
          hint="same name, different content"
        >
          <ul className="link-list">{sameName.map((e) => fileRow(nodes.get(e.target)))}</ul>
        </Group>
      )}

      {sameType.length > 0 && (
        <Group
          title={`Same type: ${displayName(nodes.get(centerType)?.label)}`}
          color="#7c3aed"
          hint="most recent files"
        >
          <ul className="link-list">{sameType.map((n) => fileRow(n))}</ul>
        </Group>
      )}
    </div>
  );
}

function Group({ title, color, hint, children }) {
  return (
    <section className="card stack" style={{ borderLeft: `3px solid ${color}` }}>
      <div>
        <strong>{title}</strong>
        {hint && <span className="muted small"> — {hint}</span>}
      </div>
      {children}
    </section>
  );
}

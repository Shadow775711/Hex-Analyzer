// src/components/file/FileTab.jsx — type, entropy (with chart), names, embedded signatures
import React from 'react';
import { cappedNames, describeEntropy, displayName, formatBytes, hex } from '../../lib/format';

export default function FileTab({ result, centerNode, onJump }) {
  if (!result) {
    return <div className="alert alert--info">Analysis in progress…</div>;
  }
  const { file = {}, embedded = [], entropy_profile: profile = [], profile_step: step } = result;
  // the backend sends at most 20 names + names_total
  const { shown: names, more } = cappedNames(centerNode);

  return (
    <div className="stack">
      <section className="card stack">
        <dl className="kv">
          <dt>Type</dt>
          <dd>
            {file.type ? (
              <>
                <strong>{displayName(file.type.name)}</strong>{' '}
                <span className="muted">.{displayName(file.type.extension)}</span>{' '}
                <span className="muted small">
                  (magic <code>{file.type.magic}</code> @ {hex(file.type.offset)})
                </span>
              </>
            ) : (
              <span className="muted">unknown — no matching signature in the database</span>
            )}
          </dd>
          <dt>Size</dt>
          <dd>{formatBytes(file.size)}</dd>
          <dt>Entropy</dt>
          <dd>
            <strong>{file.entropy?.toFixed(2) ?? '—'}</strong> bit/byte{' '}
            <span className="muted">— {describeEntropy(file.entropy)}</span>
          </dd>
          <dt>Names</dt>
          <dd>
            {names.length + more > 1 ? (
              <>
                The same file was uploaded as:{' '}
                {names.map((n) => (
                  <code key={n} style={{ marginRight: 6 }}>
                    {displayName(n)}
                  </code>
                ))}
                {more > 0 && <span className="muted">+{more} more</span>}
              </>
            ) : names[0] != null ? (
              displayName(names[0])
            ) : (
              '—'
            )}
          </dd>
          <dt>First seen</dt>
          <dd>{file.first_seen?.replace('T', ' ').slice(0, 19)}</dd>
        </dl>
      </section>

      <section className="card stack">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <p className="label" style={{ margin: 0 }}>
            Entropy profile
          </p>
          <span className="muted small">click a bar to jump to HEX</span>
        </div>
        <EntropyChart profile={profile} step={step} size={file.size} onJump={onJump} />
        <div className="entropy-legend muted small">
          <span>
            <i style={{ background: 'var(--ent-low)' }} /> &lt; 1 empty
          </span>
          <span>
            <i style={{ background: 'var(--ent-mid)' }} /> 1–7.2 data/code
          </span>
          <span>
            <i style={{ background: 'var(--ent-high)' }} /> 7.2–7.9 compression
          </span>
          <span>
            <i style={{ background: 'var(--ent-max)' }} /> ≥ 7.9 noise/encryption
          </span>
        </div>
      </section>

      <section className="card stack">
        <p className="label" style={{ margin: 0 }}>
          Embedded signatures
        </p>
        {embedded.length === 0 ? (
          <span className="muted">None found — the file contains no recognizable embedded files.</span>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Offset</th>
                <th>Type</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {embedded.map((e) => (
                <tr key={`${e.type?.id}-${e.offset}`}>
                  <td className="mono">{hex(e.offset, 8)}</td>
                  <td>{displayName(e.type?.name)}</td>
                  <td>
                    <button className="btn btn--sm" onClick={() => onJump(e.offset)}>
                      Show in HEX
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

const entropyColor = (e) =>
  e < 1 ? 'var(--ent-low)' : e < 7.2 ? 'var(--ent-mid)' : e < 7.9 ? 'var(--ent-high)' : 'var(--ent-max)';

/** Bars: height = entropy (0–8), color = category. The SVG scales to the card width. */
function EntropyChart({ profile, step, size, onJump }) {
  if (!profile.length) return <span className="muted">Empty file.</span>;
  const n = profile.length;
  return (
    <svg
      className="entropy-chart"
      viewBox={`0 0 ${n} 8`}
      preserveAspectRatio="none"
      role="img"
      aria-label="Entropy of consecutive file chunks"
    >
      {[2, 4, 6].map((y) => (
        <line key={y} x1="0" x2={n} y1={8 - y} y2={8 - y} className="entropy-grid" />
      ))}
      {profile.map((e, i) => (
        <rect
          key={i}
          x={i}
          y={8 - e}
          width={1.05}
          height={Math.max(e, 0.05)}
          fill={entropyColor(e)}
          className="entropy-bar"
          onClick={() => onJump(i * step)}
        >
          <title>{`${hex(i * step)}–${hex(Math.min((i + 1) * step, size) - 1)}: ${e.toFixed(2)} bit/B`}</title>
        </rect>
      ))}
    </svg>
  );
}

// src/App.js
import React, { useCallback, useEffect, useRef, useState } from 'react';

import GraphView from './components/graph/GraphView';
import HexDumpVirtualized from './components/hex/HexDumpVirtualized';
import FileTab from './components/file/FileTab';
import LinksTab from './components/links/LinksTab';
import ErrorBoundary from './components/ErrorBoundary';
import { uploadFile, getJob, getGraph, uploadErrorMessage } from './lib/api';
import { displayName, formatBytes } from './lib/format';
import usePreloadAll from './hooks/usePreloadAll';

const TABS = [
  { key: 'hex', label: 'Hex Dump' },
  { key: 'file', label: 'File' },
  { key: 'links', label: 'Relations' },
  { key: 'graph', label: 'Relation graph' },
];

const POLL_MS = 750;
// the graph is fetched again on entering “Relations”/“Relation graph” only if older than this
// (so files uploaded in the meantime show up, without a request on every tab switch)
const GRAPH_MAX_AGE_MS = 10_000;

export default function App() {
  // ───────── STATE
  const [file, setFile] = useState(null);

  const [jobId, setJobId] = useState(null);
  const [meta, setMeta] = useState(null); // { filename, size_bytes, sha256?, status, ... }
  const [result, setResult] = useState(null); // analysis from /jobs/{id}
  const [bytes, setBytes] = useState(null); // Uint8Array – the whole file for the hex dump
  // { jobId, graph: { center, nodes, edges } from /jobs/{id}/graph, at: fetch time } — cached per job
  const [graphEntry, setGraphEntry] = useState(null);
  const [jump, setJump] = useState(null); // { offset } — jump in the HEX viewer

  const [activeTab, setActiveTab] = useState('hex');
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState(null);

  // current jobId for the async download (so we don't store bytes of the previous file)
  const jobIdRef = useRef(null);
  useEffect(() => {
    jobIdRef.current = jobId;
  }, [jobId]);
  // mirror of graphEntry for the fetch effect (it must not re-run when the graph arrives)
  const graphEntryRef = useRef(null);

  // ───────── SWITCH TO A JOB (new upload or “Open” from the graph)
  const openJob = useCallback((id, initialMeta = null) => {
    // synchronously, not only in the effect: an async result (preload, graph) that finishes
    // before the re-render must already see the new job and drop data of the previous one
    jobIdRef.current = id;
    setError(null);
    setMeta(initialMeta);
    setResult(null);
    setBytes(null);
    graphEntryRef.current = null;
    setGraphEntry(null);
    setJump(null);
    setJobId(id);
  }, []);

  const handleUpload = async () => {
    if (!file) return;
    setError(null);
    try {
      setUploading(true);
      const res = await uploadFile(file);
      openJob(res.job_id, res.meta); // meta right away → preload can start
      setActiveTab('hex');
    } catch (err) {
      console.error('[App] upload error:', err);
      setError(uploadErrorMessage(err));
    } finally {
      setUploading(false);
    }
  };

  const jumpTo = useCallback((offset) => {
    setJump({ offset });
    setActiveTab('hex');
  }, []);

  // ───────── POLLING (GET /jobs/{job_id}) — until "done" or "error"
  useEffect(() => {
    if (!jobId) return;
    let alive = true;
    let timer = null;

    async function poll() {
      try {
        const info = await getJob(jobId);
        if (!alive) return;

        setMeta((prev) => ({ ...(prev || {}), ...info }));
        if (info.result) setResult(info.result);

        if (info.status === 'error') {
          setError(`Analysis failed: ${info.analysis_error || 'unknown error'}`);
          return; // stop polling
        }
        if (!info.analysis_ready) {
          timer = setTimeout(poll, POLL_MS);
        }
      } catch (e) {
        if (alive) {
          console.error('[App] job poll error:', e);
          setError('Error while reading the job status.');
        }
      }
    }

    poll();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [jobId]);

  // ───────── GRAPH — cached per job; refreshed when entering “Relations”/“Relation graph”
  // if older than GRAPH_MAX_AGE_MS, so files uploaded later show up too
  const analysisDone = meta?.status === 'done';
  useEffect(() => {
    if (!jobId || !analysisDone || activeTab === 'hex') return;
    const cached = graphEntryRef.current;
    if (cached?.jobId === jobId) {
      // “File” only needs the names of the center node — any cached graph will do
      if (activeTab === 'file' || Date.now() - cached.at < GRAPH_MAX_AGE_MS) return;
    }
    const forJob = jobId; // the job this request belongs to
    const ctrl = new AbortController();
    getGraph(forJob, { signal: ctrl.signal })
      .then((g) => {
        if (ctrl.signal.aborted || jobIdRef.current !== forJob) return; // another job in the meantime
        const entry = { jobId: forJob, graph: g, at: Date.now() };
        graphEntryRef.current = entry;
        setGraphEntry(entry);
      })
      .catch((e) => {
        if (!ctrl.signal.aborted) console.error('[App] graph error:', e);
      });
    return () => ctrl.abort();
  }, [jobId, analysisDone, activeTab]);
  const graph = graphEntry?.jobId === jobId ? graphEntry.graph : null;

  // ───────── AUTO-DOWNLOAD OF THE WHOLE FILE INTO MEMORY
  const totalSize = meta?.size_bytes ?? 0;
  const { preload, loading, progress } = usePreloadAll(jobId, totalSize);

  useEffect(() => {
    if (!jobId || !totalSize) return;
    if (bytes || loading) return; // already have it or in progress

    const forJob = jobId;
    (async () => {
      try {
        const buf = await preload(8 * 1024 * 1024); // 8 MB pages
        if (buf && jobIdRef.current === forJob) setBytes(buf); // don't store bytes of the previous file
      } catch (e) {
        console.error('[App] preload error:', e);
        setError('Error while downloading the file data.');
      }
    })();
  }, [jobId, totalSize, bytes, loading, preload]);

  const centerNode = graph?.nodes?.find?.((n) => n?.id === graph.center);

  // ───────── UI
  return (
    <>
      <header className="header">
        <div>
          <h1>Hex Dump Analyzer</h1>
          <div className="muted small">HEX viewer · types and entropy · relations between files</div>
        </div>

        <div className="row">
          {/* <label> clicks the hidden <input type="file"> — no library needed */}
          <label className="btn">
            {file ? 'Change file' : 'Choose file'}
            <input
              type="file"
              className="visually-hidden"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
          </label>

          <button className="btn btn--primary" onClick={handleUpload} disabled={!file || uploading}>
            {uploading ? 'Uploading…' : 'Analyze'}
          </button>
        </div>
      </header>

      <main className="main">
        {error && (
          <div className="alert alert--error" role="alert">
            {error}
          </div>
        )}

        {!jobId ? (
          <section className="card stack center">
            {uploading ? (
              <div className="spinner" aria-label="Uploading" />
            ) : (
              <span className="muted">Choose a file and click “Analyze”.</span>
            )}
            {file && (
              <span className="small">
                Selected: <code>{displayName(file.name)}</code>
              </span>
            )}
          </section>
        ) : (
          <div>
            <div className="file-bar">
              <strong className="ellipsis">
                {meta?.filename != null ? displayName(meta.filename) : '…'}
              </strong>
              <span className="muted small">
                {formatBytes(meta?.size_bytes)}
                {result?.file?.type && ` · ${displayName(result.file.type.name)}`}
                {meta?.status && meta.status !== 'done' && ` · ${STATUS[meta.status] ?? meta.status}…`}
              </span>
            </div>

            <div className="tabs" role="tablist">
              {TABS.map((t) => (
                <button
                  key={t.key}
                  className="tab"
                  role="tab"
                  aria-selected={activeTab === t.key}
                  onClick={() => setActiveTab(t.key)}
                >
                  {t.label}
                </button>
              ))}
            </div>

            <div style={{ paddingTop: 16 }} role="tabpanel">
              {/* resetKey: new data (e.g. another job) clears a previous error */}
              {activeTab === 'hex' && (
                <ErrorBoundary resetKey={bytes}>
                  <HexTab
                    sha={meta?.sha256 ?? ''}
                    bytes={bytes}
                    loading={loading}
                    progress={progress}
                    jump={jump}
                  />
                </ErrorBoundary>
              )}
              {activeTab === 'file' && (
                <ErrorBoundary resetKey={result}>
                  <FileTab result={result} centerNode={centerNode} onJump={jumpTo} />
                </ErrorBoundary>
              )}
              {activeTab === 'links' &&
                (analysisDone ? (
                  <ErrorBoundary resetKey={graph}>
                    <LinksTab graph={graph} currentJobId={jobId} onOpenJob={openJob} />
                  </ErrorBoundary>
                ) : (
                  <div className="alert alert--info">Analysis in progress…</div>
                ))}
              {activeTab === 'graph' && (
                <section className="card">
                  {analysisDone ? (
                    <ErrorBoundary resetKey={graph}>
                      <GraphView graph={graph} currentJobId={jobId} onOpenJob={openJob} />
                    </ErrorBoundary>
                  ) : (
                    <div className="muted">Analysis in progress…</div>
                  )}
                </section>
              )}
            </div>
          </div>
        )}
      </main>
    </>
  );
}

const STATUS = { queued: 'queued', processing: 'analyzing' };

function HexTab({ sha, bytes, loading, progress, jump }) {
  return (
    <section className="card stack">
      <div>
        <p className="label">SHA-256:</p>
        <div className="row">
          <input className="input" value={sha} readOnly placeholder="computing…" />
          <button className="btn" onClick={() => navigator.clipboard?.writeText(sha)} disabled={!sha}>
            ⧉ Copy
          </button>
        </div>
      </div>

      <div>
        <p className="label">HEX Dump:</p>
        {bytes ? (
          <HexDumpVirtualized bytes={bytes} cols={16} height={520} rowHeight={22} jumpTo={jump} />
        ) : loading ? (
          <div className="stack stack--tight">
            <span className="muted small">Downloading data… {(progress * 100).toFixed(1)}%</span>
            <progress className="progress" value={progress} max={1} />
          </div>
        ) : (
          <span className="muted">Waiting for data…</span>
        )}
      </div>
    </section>
  );
}

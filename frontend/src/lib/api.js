// src/lib/api.js
// Defaults to /api on the same address (Docker: Caddy → nginx, dev: Vite proxy).
const API_BASE = import.meta.env.VITE_API_URL?.trim() || '/api';

// Header required by the backend for state-changing requests (POST/DELETE) — CSRF protection.
// A foreign site cannot add it without CORS consent, and an HTML form adds no headers at all.
const CSRF_HEADERS = { 'X-Hex-Analyzer': '1' };

const API = (p) => `${API_BASE}${p}`;
// job id in a URL path — encoded anyway (defence in depth, ids come from the server)
const jobPath = (jobId) => `/jobs/${encodeURIComponent(jobId)}`;

const MAX_DETAIL = 200;

/**
 * Error for a non-2xx response: `status` for the caller, and only a short excerpt of the body
 * in the message (it may be a whole HTML error page or carry server details).
 */
async function httpError(what, res) {
  const body = await res.text().catch(() => '');
  const excerpt = body.length > MAX_DETAIL ? `${body.slice(0, MAX_DETAIL)}…` : body;
  const err = new Error(`${what} HTTP ${res.status}${excerpt ? `: ${excerpt}` : ''}`);
  err.status = res.status;
  return err;
}

/** User-facing message for a failed upload (uses err.status from uploadFile) */
export function uploadErrorMessage(err) {
  switch (err?.status) {
    case 413:
      return 'File is too large (limit 100 MB).';
    case 503:
      return 'The analysis queue is full — try again in a moment.';
    case 507:
      return 'The server is out of free disk space — try again later.';
    default:
      return 'Error while uploading the file.';
  }
}

/** POST /upload  — field "file" (FormData) */
export async function uploadFile(file, { signal } = {}) {
  const fd = new FormData();
  fd.append('file', file);

  const res = await fetch(API('/upload'), {
    method: 'POST',
    headers: CSRF_HEADERS,
    body: fd,
    signal,
  });

  if (!res.ok) throw await httpError('Upload', res);
  return res.json(); // { job_id, status: "queued", meta }
}

/** GET /jobs/{id} — meta + status (+ result when ready) */
export async function getJob(jobId, { signal } = {}) {
  const res = await fetch(API(jobPath(jobId)), { signal });
  if (!res.ok) throw await httpError('Job', res);
  return res.json();
}

/** GET /jobs/{id}/bytes?offset=&length= — binary data as Uint8Array */
export async function fetchBytes(jobId, offset, length, { signal } = {}) {
  const url = API(`${jobPath(jobId)}/bytes?offset=${offset}&length=${length}`);
  const res = await fetch(url, { signal });
  if (!res.ok) throw await httpError('Bytes', res);

  return new Uint8Array(await res.arrayBuffer());
}

/** GET /jobs/{id}/graph — file relations: { center, nodes, edges } */
export async function getGraph(jobId, { minSimilarity = 0.05, limit = 25, signal } = {}) {
  const url = API(`${jobPath(jobId)}/graph?min_similarity=${minSimilarity}&limit=${limit}`);
  const res = await fetch(url, { signal });
  if (!res.ok) throw await httpError('Graph', res);
  return res.json();
}

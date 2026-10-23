import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import { getGraph, getJob, uploadFile } from './lib/api';

vi.mock('./lib/api', async (importOriginal) => ({
  ...(await importOriginal()),
  uploadFile: vi.fn(),
  getJob: vi.fn(),
  getGraph: vi.fn(),
}));
// no byte download in these tests
vi.mock('./hooks/usePreloadAll', () => ({
  default: () => ({ preload: async () => null, loading: false, progress: 0 }),
}));

const deferred = () => {
  let resolve;
  const promise = new Promise((r) => (resolve = r));
  return { promise, resolve };
};

const graphFor = (jobId, label, others = []) => ({
  center: 'f:1',
  nodes: [{ id: 'f:1', kind: 'file', label, names: [label], job_id: jobId, size: 1 }, ...others],
  edges: others.map((n) => ({ source: 'f:1', target: n.id, relation: 'same_name' })),
});

async function uploadAndWait() {
  fireEvent.change(document.querySelector('input[type=file]'), {
    target: { files: [new File(['x'], 'a.bin')] },
  });
  fireEvent.click(screen.getByText('Analyze'));
  await screen.findByText('Relations');
}

const tab = (name) => fireEvent.click(screen.getByRole('tab', { name }));

describe('App', () => {
  let now;
  beforeEach(() => {
    now = 1_000_000;
    vi.spyOn(Date, 'now').mockImplementation(() => now);
    vi.spyOn(console, 'error').mockImplementation(() => {});
    // GraphView measures its container (jsdom has no ResizeObserver)
    vi.stubGlobal(
      'ResizeObserver',
      class {
        observe() {}
        disconnect() {}
      }
    );
    uploadFile.mockResolvedValue({ job_id: 'j1', meta: { filename: 'a.bin', size_bytes: 0 } });
    getJob.mockImplementation(async (id) => ({
      job_id: id,
      filename: `${id}.bin`,
      size_bytes: 0,
      status: 'done',
      analysis_ready: true,
      result: { file: { size: 1, entropy: 1, type: null }, embedded: [], entropy_profile: [] },
    }));
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it.each([
    [413, /too large/],
    [503, /queue is full/],
    [507, /disk space/],
    [500, /Error while uploading/],
  ])('upload error %s → friendly message', async (status, re) => {
    uploadFile.mockRejectedValue(Object.assign(new Error(`Upload HTTP ${status}`), { status }));
    render(<App />);
    fireEvent.change(document.querySelector('input[type=file]'), {
      target: { files: [new File(['x'], 'a.bin')] },
    });
    fireEvent.click(screen.getByText('Analyze'));
    expect(await screen.findByRole('alert')).toHaveTextContent(re);
  });

  it('shows the generic analysis error from the backend', async () => {
    getJob.mockResolvedValue({ status: 'error', analysis_error: 'Analysis failed', size_bytes: 0 });
    render(<App />);
    await uploadAndWait();
    expect(await screen.findByRole('alert')).toHaveTextContent('Analysis failed: Analysis failed');
  });

  it('caches the graph per job, refreshes it on entering Relations after 10 s', async () => {
    getGraph.mockResolvedValue(graphFor('j1', 'one.bin'));
    render(<App />);
    await uploadAndWait();
    tab('Relations');
    await waitFor(() => expect(getGraph).toHaveBeenCalledTimes(1));
    tab('File');
    tab('Relation graph');
    tab('Relations');
    await act(async () => {});
    expect(getGraph).toHaveBeenCalledTimes(1);

    now += 11_000;
    tab('File'); // “File” is happy with any cached graph
    await act(async () => {});
    expect(getGraph).toHaveBeenCalledTimes(1);
    tab('Relations'); // stale → fetched again, so new uploads show up
    await waitFor(() => expect(getGraph).toHaveBeenCalledTimes(2));
  });

  it('a graph of the previous job arriving late is not shown for the new job', async () => {
    const other = { id: 'f:2', kind: 'file', label: 'two.bin', names: ['two.bin'], job_id: 'j2', size: 1 };
    getGraph.mockResolvedValueOnce(graphFor('j1', 'one.bin', [other]));
    render(<App />);
    await uploadAndWait();
    tab('Relations');
    await screen.findByText('two.bin');

    // a refresh for j1 hangs, then the user opens j2 — the mock ignores the abort signal
    now += 11_000;
    const lateJ1 = deferred();
    const forJ2 = deferred();
    getGraph.mockImplementation((id) => (id === 'j1' ? lateJ1.promise : forJ2.promise));
    tab('File');
    tab('Relations');
    await waitFor(() => expect(getGraph).toHaveBeenCalledTimes(2));
    fireEvent.click(screen.getByText('Open'));
    await waitFor(() => expect(getGraph).toHaveBeenLastCalledWith('j2', expect.anything()));

    expect(screen.getByText(/Loading relations/)).toBeInTheDocument();
    const fresh = {
      id: 'f:3',
      kind: 'file',
      label: 'FRESH.bin',
      names: ['FRESH.bin'],
      job_id: null,
      size: 1,
    };
    await act(async () => forJ2.resolve(graphFor('j2', 'two.bin', [fresh])));
    expect(await screen.findByText('FRESH.bin')).toBeInTheDocument();

    // j1's response comes in last — it must not replace j2's graph
    const stale = {
      id: 'f:9',
      kind: 'file',
      label: 'STALE.bin',
      names: ['STALE.bin'],
      job_id: null,
      size: 1,
    };
    await act(async () => lateJ1.resolve(graphFor('j1', 'one.bin', [stale])));
    expect(screen.queryByText('STALE.bin')).toBeNull();
    expect(screen.getByText('FRESH.bin')).toBeInTheDocument();
  });

  it('a malformed response shows an error in the tab instead of blanking the app', async () => {
    const swallow = (e) => e.preventDefault();
    window.addEventListener('error', swallow);
    try {
      getGraph.mockResolvedValue({ center: 'f:1', nodes: [{ id: 'f:1', kind: 'file', names: 5 }], edges: 7 });
      render(<App />);
      await uploadAndWait();
      tab('Relations');
      expect(await screen.findByRole('alert')).toHaveTextContent(
        'Something went wrong displaying this view.'
      );
      expect(screen.getByText('Hex Dump Analyzer')).toBeInTheDocument();
    } finally {
      window.removeEventListener('error', swallow);
    }
  });
});

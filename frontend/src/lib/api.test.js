import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchBytes, getGraph, getJob, uploadErrorMessage, uploadFile } from './api';

const respond = (status, body = '') => vi.fn(async () => new Response(body, { status }));

describe('api', () => {
  let fetchMock;
  beforeEach(() => {
    fetchMock = respond(200, '{}');
    vi.stubGlobal('fetch', fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  it('encodes the job id in URLs', async () => {
    await getJob('a/../b?x=1#y');
    await getGraph('a/b');
    expect(fetchMock.mock.calls[0][0]).toBe('/api/jobs/a%2F..%2Fb%3Fx%3D1%23y');
    expect(fetchMock.mock.calls[1][0]).toMatch(/^\/api\/jobs\/a%2Fb\/graph\?/);
  });

  it.each([
    ['uploadFile', () => uploadFile(new Blob(['x']))],
    ['getJob', () => getJob('j1')],
    ['getGraph', () => getGraph('j1')],
    ['fetchBytes', () => fetchBytes('j1', 0, 10)],
  ])('%s attaches the HTTP status to the error', async (_, call) => {
    vi.stubGlobal('fetch', respond(503, '{"detail":"Analysis queue is full, try again later"}'));
    await expect(call()).rejects.toMatchObject({ status: 503 });
  });

  it('puts only a short excerpt of the response body into the message', async () => {
    vi.stubGlobal('fetch', respond(500, 'x'.repeat(5000)));
    const err = await getJob('j1').catch((e) => e);
    expect(err.status).toBe(500);
    expect(err.message.length).toBeLessThan(260);
  });

  it('upload sends the CSRF header', async () => {
    await uploadFile(new Blob(['x']));
    expect(fetchMock.mock.calls[0][1].headers).toMatchObject({ 'X-Hex-Analyzer': '1' });
  });
});

describe('uploadErrorMessage', () => {
  it.each([
    [413, /too large/],
    [503, /queue is full/],
    [507, /disk space/],
    [500, /Error while uploading/],
    [undefined, /Error while uploading/],
  ])('%s → %s', (status, re) => {
    expect(uploadErrorMessage(Object.assign(new Error('x'), { status }))).toMatch(re);
  });
});

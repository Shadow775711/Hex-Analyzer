import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchBytes } from '../lib/api';

const MAX_ATTEMPTS = 5;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * Downloads the whole file in parallel chunks into a single Uint8Array.
 * Changing jobId aborts the ongoing download (preload then returns null).
 */
export default function usePreloadAll(jobId, totalSize) {
  const [progress, setProgress] = useState(0);
  const [loading, setLoading] = useState(false);
  const controllerRef = useRef(null);

  // different file → discard the old download
  useEffect(() => () => controllerRef.current?.abort(), [jobId]);

  const preload = useCallback(
    async (pageSize = 8 * 1024 * 1024, concurrency = 6) => {
      if (!jobId || !totalSize) return null;
      const controller = new AbortController();
      controllerRef.current = controller;
      setLoading(true);
      setProgress(0);

      try {
        const full = new Uint8Array(totalSize);

        const ranges = [];
        for (let off = 0; off < totalSize; off += pageSize) {
          ranges.push({ off, len: Math.min(pageSize, totalSize - off) });
        }

        let loaded = 0;
        let nextIdx = 0;

        async function worker() {
          while (nextIdx < ranges.length) {
            const { off, len } = ranges[nextIdx++];

            // network error → up to MAX_ATTEMPTS tries with growing delay; 4xx error or abort → stop
            for (let attempt = 1; ; attempt++) {
              try {
                const chunk = await fetchBytes(jobId, off, len, { signal: controller.signal });
                full.set(chunk, off);
                loaded += chunk.length;
                setProgress(loaded / totalSize);
                break;
              } catch (e) {
                if (controller.signal.aborted) throw e;
                if (e?.status === 410)
                  throw new Error('Source file is no longer available (410).', { cause: e });
                if ((e?.status >= 400 && e?.status < 500) || attempt >= MAX_ATTEMPTS) throw e;
                await sleep(Math.min(2000, 150 * Math.pow(2, attempt)));
              }
            }
          }
        }

        await Promise.all(Array.from({ length: Math.min(concurrency, ranges.length) }, () => worker()));
        return full;
      } catch (e) {
        if (controller.signal.aborted) return null; // file was switched — not an error
        throw e;
      } finally {
        // only “our” download clears the flag — a newer one may have already started
        if (controllerRef.current === controller) {
          controllerRef.current = null;
          setLoading(false);
        }
      }
    },
    [jobId, totalSize]
  );

  return { preload, loading, progress };
}

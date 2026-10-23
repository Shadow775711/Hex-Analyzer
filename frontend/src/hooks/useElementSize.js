import { useCallback, useRef, useState } from 'react';

/**
 * Measures an element via ResizeObserver (replacement for useElementSize from @mantine/hooks).
 * Returns a callback ref: <div ref={ref}> — also works when the node changes.
 */
export default function useElementSize() {
  const [size, setSize] = useState({ width: 0, height: 0 });
  const observerRef = useRef(null);

  const ref = useCallback((node) => {
    observerRef.current?.disconnect();
    observerRef.current = null;
    if (!node) return;

    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      // same size → same object, to avoid needless re-renders
      setSize((prev) => (prev.width === width && prev.height === height ? prev : { width, height }));
    });
    observer.observe(node);
    observerRef.current = observer;
  }, []);

  return { ref, ...size };
}

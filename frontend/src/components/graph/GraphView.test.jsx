import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import GraphView from './GraphView';

// The real canvas graph does not run in jsdom — the mock records props and lets us "click" a node
const fgProps = vi.hoisted(() => ({ current: null }));
vi.mock('react-force-graph-2d', async () => {
  const React = await import('react');
  return {
    default: React.forwardRef(function ForceGraph2DMock(props, _ref) {
      fgProps.current = props;
      return (
        <div data-testid="fg">
          {props.graphData.nodes.map((n) => (
            <button key={n.id} onClick={() => props.onNodeClick(n)}>
              node {n.id}
            </button>
          ))}
        </div>
      );
    }),
  };
});
// known width right away (jsdom has no layout / ResizeObserver)
vi.mock('../../hooks/useElementSize', () => ({
  default: () => ({ ref: () => {}, width: 600, height: 560 }),
}));

const graph = {
  center: 'f:1',
  nodes: [
    {
      id: 'f:1',
      kind: 'file',
      current: true,
      label: 'report\u202efdp.exe',
      names: ['report\u202efdp.exe', 'b.exe'],
      names_total: 42,
      job_id: 'j1',
      size: 10,
      type: { name: 'PE\u200b executable' },
    },
    { id: 't:1', kind: 'type', label: 'PE executable', extension: 'e\u2066xe', magic: '4D5A', offset: 0 },
  ],
  edges: [{ source: 'f:1', target: 't:1', relation: 'is_type', name: '<img src=x onerror=alert(1)>' }],
};

describe('GraphView', () => {
  it('disables the HTML tooltips of force-graph (node and link labels)', () => {
    render(<GraphView graph={graph} currentJobId="j1" onOpenJob={() => {}} />);
    expect(fgProps.current.nodeLabel(graph.nodes[0])).toBe('');
    expect(fgProps.current.linkLabel(graph.edges[0])).toBe('');
  });

  it('side panel: invisible characters made visible, names capped with “+N more”', () => {
    render(<GraphView graph={graph} currentJobId="j1" onOpenJob={() => {}} />);
    fireEvent.click(screen.getByText('node f:1'));
    expect(screen.getAllByText('report⟨U+202E⟩fdp.exe', { exact: false }).length).toBeGreaterThan(0);
    expect(screen.getByText('+40 more')).toBeInTheDocument();
    expect(screen.getByText('PE⟨U+200B⟩ executable')).toBeInTheDocument();

    fireEvent.click(screen.getByText('node t:1'));
    expect(screen.getByText('.e⟨U+2066⟩xe')).toBeInTheDocument();
  });

  it('canvas label: visible markers and truncation by code points', () => {
    render(<GraphView graph={graph} currentJobId="j1" onOpenJob={() => {}} />);
    const texts = [];
    const ctx = {
      beginPath() {},
      arc() {},
      fill() {},
      stroke() {},
      roundRect() {},
      fillText: (t) => texts.push(t),
    };
    fgProps.current.nodeCanvasObject({ ...graph.nodes[0], x: 0, y: 0 }, ctx, 1);
    fgProps.current.nodeCanvasObject({ id: 'f:9', kind: 'file', label: '😀'.repeat(40), x: 0, y: 0 }, ctx, 1);
    fgProps.current.nodeCanvasObject({ id: 'f:8', kind: 'file', x: 0, y: 0 }, ctx, 1); // no label
    expect(texts[0]).toBe('report⟨U+202E⟩fdp.exe');
    expect(texts[1]).toBe(`${'😀'.repeat(27)}…`);
    expect(texts[2]).toBe('');
  });
});

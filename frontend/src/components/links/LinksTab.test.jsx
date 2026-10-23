import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import LinksTab from './LinksTab';

const png = { id: 1, name: 'PNG image', extension: 'png' };
const graph = {
  center: 'f:1',
  nodes: [
    {
      id: 'f:1',
      kind: 'file',
      current: true,
      label: 'a.png',
      names: ['a.png', 'copy.png'],
      job_id: 'j1',
      size: 100,
      type: png,
    },
    { id: 'f:2', kind: 'file', label: 'a_v2.png', names: ['a_v2.png'], job_id: 'j2', size: 100, type: png },
    {
      id: 'f:3',
      kind: 'file',
      label: '<img src=x onerror=alert(1)>',
      names: [],
      job_id: null,
      size: 5,
      type: png,
    },
    { ...png, id: 't:1', kind: 'type', label: 'PNG image' },
  ],
  edges: [
    { source: 'f:1', target: 't:1', relation: 'is_type' },
    { source: 'f:2', target: 't:1', relation: 'is_type' },
    { source: 'f:3', target: 't:1', relation: 'is_type' },
    { source: 'f:1', target: 'f:2', relation: 'similar', weight: 0.98, label: '98%' },
  ],
};

describe('LinksTab', () => {
  it('shows groups: identical, similar, same type', () => {
    render(<LinksTab graph={graph} currentJobId="j1" onOpenJob={() => {}} />);
    expect(screen.getByText(/Identical/)).toBeInTheDocument();
    expect(screen.getByText('copy.png')).toBeInTheDocument();
    expect(screen.getByText('98%')).toBeInTheDocument();
    expect(screen.getByText(/Same type: PNG image/)).toBeInTheDocument();
  });

  it('“Open” switches to the file, and an unavailable file has no button', () => {
    const onOpen = vi.fn();
    render(<LinksTab graph={graph} currentJobId="j1" onOpenJob={onOpen} />);
    fireEvent.click(screen.getAllByText('Open')[0]);
    expect(onOpen).toHaveBeenCalledWith('j2');
    // f:2 is in both “Similar” and “Same type”; f:3 (no job_id) has no button
    expect(screen.getAllByText('Open')).toHaveLength(2);
  });

  it('renders file names as text, not HTML', () => {
    const { container } = render(<LinksTab graph={graph} currentJobId="j1" onOpenJob={() => {}} />);
    expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeInTheDocument();
    expect(container.querySelector('img')).toBeNull();
  });

  it('empty graph → no relations message', () => {
    const lonely = { center: 'f:1', nodes: [{ ...graph.nodes[0], names: ['a.png'] }], edges: [] };
    render(<LinksTab graph={lonely} currentJobId="j1" onOpenJob={() => {}} />);
    expect(screen.getByText(/No relations yet/)).toBeInTheDocument();
  });

  it('capped names: “+N more” for the current file and in “also as”', () => {
    const g = {
      ...graph,
      nodes: graph.nodes.map((n) =>
        n.id === 'f:1'
          ? { ...n, names_total: 30 }
          : n.id === 'f:2'
            ? { ...n, names: ['a_v2.png', 'old.png'], names_total: 7 }
            : n
      ),
    };
    render(<LinksTab graph={g} currentJobId="j1" onOpenJob={() => {}} />);
    expect(screen.getByText('+28 more')).toBeInTheDocument();
    expect(screen.getAllByText(/also as: old\.png, \+5 more/).length).toBeGreaterThan(0);
  });

  it('invisible characters in names and types are made visible', () => {
    const g = {
      ...graph,
      nodes: [
        { ...graph.nodes[0], names: ['a.png', 'x\u202Egnp.exe'] },
        { ...graph.nodes[1], label: 'v\u200B2.png' },
        graph.nodes[2],
        { ...graph.nodes[3], label: 'PNG\u2066 image' },
      ],
    };
    render(<LinksTab graph={g} currentJobId="j1" onOpenJob={() => {}} />);
    expect(screen.getByText('x⟨U+202E⟩gnp.exe')).toBeInTheDocument();
    expect(screen.getAllByText('v⟨U+200B⟩2.png').length).toBeGreaterThan(0);
    expect(screen.getByText(/Same type: PNG⟨U\+2066⟩ image/)).toBeInTheDocument();
  });

  it('edges to missing nodes and a missing node list do not crash', () => {
    const broken = {
      center: 'f:1',
      nodes: [graph.nodes[0]],
      edges: [
        { source: 'f:1', target: 'f:404', relation: 'similar', weight: 0.5, label: '50%' },
        { source: 'f:1', target: 't:404', relation: 'contains', label: '1×' },
      ],
    };
    render(<LinksTab graph={broken} currentJobId="j1" onOpenJob={() => {}} />);
    expect(screen.getByText(/Identical/)).toBeInTheDocument();
    render(<LinksTab graph={{ center: 'f:1' }} currentJobId="j1" onOpenJob={() => {}} />);
    expect(screen.getByText(/No relations yet/)).toBeInTheDocument();
  });
});

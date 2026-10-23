import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import FileTab from './FileTab';

const zip = { id: 12, name: 'ZIP archive', extension: 'zip', magic: '504B0304', offset: 0 };
const result = {
  file: { id: 1, size: 300000, entropy: 7.99, type: null, first_seen: '2026-10-23T10:00:00' },
  entropy_profile: [7.9, 7.95, 0.2],
  profile_step: 4096,
  embedded: [{ type: zip, offset: 10000 }],
};

describe('FileTab', () => {
  it('unknown type, entropy with description, profile as bars', () => {
    const { container } = render(<FileTab result={result} onJump={() => {}} />);
    expect(screen.getByText(/unknown/)).toBeInTheDocument();
    expect(screen.getByText(/compression or encryption/)).toBeInTheDocument();
    expect(container.querySelectorAll('.entropy-chart rect')).toHaveLength(3);
  });

  it('“Show in HEX” and clicking a bar jump to the offset', () => {
    const onJump = vi.fn();
    const { container } = render(<FileTab result={result} onJump={onJump} />);
    fireEvent.click(screen.getByText('Show in HEX'));
    expect(onJump).toHaveBeenLastCalledWith(10000);
    fireEvent.click(container.querySelectorAll('.entropy-chart rect')[2]);
    expect(onJump).toHaveBeenLastCalledWith(2 * 4096);
  });

  it('analysis in progress — message', () => {
    render(<FileTab result={null} onJump={() => {}} />);
    expect(screen.getByText(/Analysis in progress/)).toBeInTheDocument();
  });

  it('names: invisible characters made visible, capped list with “+N more”', () => {
    const center = { names: ['a\u202Efdp.exe', 'b.exe'], names_total: 25 };
    render(<FileTab result={result} centerNode={center} onJump={() => {}} />);
    expect(screen.getByText('a⟨U+202E⟩fdp.exe')).toBeInTheDocument();
    expect(screen.getByText('+23 more')).toBeInTheDocument();
  });

  it('names without names_total — no “more”', () => {
    render(<FileTab result={result} centerNode={{ names: ['a.bin', 'b.bin'] }} onJump={() => {}} />);
    expect(screen.getByText('b.bin')).toBeInTheDocument();
    expect(screen.queryByText(/more$/)).toBeNull();
  });

  it('type name/extension and embedded type: invisible characters made visible', () => {
    const r = {
      ...result,
      file: { ...result.file, type: { ...zip, name: 'Z\u200BIP', extension: 'z\uFEFFip' } },
      embedded: [{ type: { ...zip, name: 'P\u2066NG' }, offset: 1 }],
    };
    render(<FileTab result={r} onJump={() => {}} />);
    expect(screen.getByText('Z⟨U+200B⟩IP')).toBeInTheDocument();
    expect(screen.getByText('.z⟨U+FEFF⟩ip')).toBeInTheDocument();
    expect(screen.getByText('P⟨U+2066⟩NG')).toBeInTheDocument();
  });

  it('missing entropy does not crash', () => {
    const r = { ...result, file: { ...result.file, entropy: undefined } };
    render(<FileTab result={r} onJump={() => {}} />);
    expect(screen.getByText('Entropy')).toBeInTheDocument();
  });
});

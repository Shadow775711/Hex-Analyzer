import { describe, expect, it } from 'vitest';
import { cappedNames, describeEntropy, displayName, formatBytes, hex, truncate } from './format';

describe('hex', () => {
  it('formats with a 0x prefix and uppercase letters', () => {
    expect(hex(255)).toBe('0xFF');
    expect(hex(10000, 8)).toBe('0x00002710');
  });
  it('treats a missing value as zero', () => {
    expect(hex(undefined)).toBe('0x0');
  });
});

describe('formatBytes', () => {
  it('small values in bytes', () => {
    expect(formatBytes(512)).toBe('512 B');
  });
  it('larger ones in KB/MB with the exact byte count', () => {
    expect(formatBytes(400008)).toMatch(/^390\.6 KB \(400,008 B\)$/);
  });
  it('missing value → dash', () => {
    expect(formatBytes(null)).toBe('—');
  });
});

describe('describeEntropy', () => {
  it.each([
    [0, /repetitions/],
    [4.5, /text/],
    [6.5, /machine code/],
    [7.5, /compressed/],
    [7.99, /encryption/],
  ])('%s bit/B → %s', (e, re) => {
    expect(describeEntropy(e)).toMatch(re);
  });
});

describe('displayName', () => {
  it('leaves ordinary names (also non-ASCII) untouched', () => {
    expect(displayName('zdjęcie 1.png')).toBe('zdjęcie 1.png');
    expect(displayName('🙂.txt')).toBe('🙂.txt');
  });
  it('makes a bidi override visible (RLO spoofing “exe” as “pdf”)', () => {
    expect(displayName('evil\u202Efdp.exe')).toBe('evil⟨U+202E⟩fdp.exe');
  });
  it.each([
    ['\u202A', 'U+202A'],
    ['\u202D', 'U+202D'],
    ['\u2066', 'U+2066'],
    ['\u2069', 'U+2069'],
    ['\u200B', 'U+200B'],
    ['\u200F', 'U+200F'],
    ['\uFEFF', 'U+FEFF'],
    ['\u0000', 'U+0000'],
    ['\n', 'U+000A'],
    ['\u007F', 'U+007F'],
  ])('%j → ⟨%s⟩', (c, code) => {
    expect(displayName(`a${c}b`)).toBe(`a⟨${code}⟩b`);
  });
  it('replaces every occurrence', () => {
    expect(displayName('\u200B\u200B')).toBe('⟨U+200B⟩⟨U+200B⟩');
  });
  it('missing value → empty string, numbers as text', () => {
    expect(displayName(null)).toBe('');
    expect(displayName(undefined)).toBe('');
    expect(displayName(7)).toBe('7');
  });
});

describe('truncate', () => {
  it('short text unchanged, long text with an ellipsis', () => {
    expect(truncate('abc', 5)).toBe('abc');
    expect(truncate('abcdef', 4)).toBe('abc…');
  });
  it('does not split a surrogate pair', () => {
    const out = truncate('😀😀😀😀', 3);
    expect(out).toBe('😀😀…');
  });
  it('missing value → empty string', () => {
    expect(truncate(undefined, 3)).toBe('');
  });
});

describe('cappedNames', () => {
  it('counts names the backend did not send', () => {
    expect(cappedNames({ names: ['a', 'b'], names_total: 30 })).toEqual({ shown: ['a', 'b'], more: 28 });
  });
  it('works without names_total and without names', () => {
    expect(cappedNames({ names: ['a', 'b'] })).toEqual({ shown: ['a', 'b'], more: 0 });
    expect(cappedNames(undefined)).toEqual({ shown: [], more: 0 });
  });
  it('shows at most 20 even if more were sent', () => {
    const names = Array.from({ length: 25 }, (_, i) => `n${i}`);
    const { shown, more } = cappedNames({ names });
    expect(shown).toHaveLength(20);
    expect(more).toBe(5);
  });
});

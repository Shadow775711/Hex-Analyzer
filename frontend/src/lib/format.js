// Small formatting helpers shared by the tabs and the graph

export const hex = (n, pad = 1) =>
  `0x${Number(n ?? 0)
    .toString(16)
    .toUpperCase()
    .padStart(pad, '0')}`;

export function formatBytes(n) {
  if (n == null) return '—';
  const units = ['B', 'KB', 'MB', 'GB'];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${i ? v.toFixed(1) : v} ${units[i]}${i ? ` (${n.toLocaleString('en-US')} B)` : ''}`;
}

/** What the entropy means — in human terms */
export function describeEntropy(e) {
  if (e == null) return '';
  if (e < 1) return 'almost only repetitions (padding, empty areas)';
  if (e < 5) return 'text, code, structured data';
  if (e < 7.2) return 'machine code or mixed data';
  if (e < 7.9) return 'compressed data (e.g. images, archives)';
  return 'noise — compression or encryption';
}

// Control (Cc) and format (Cf) characters: bidi overrides (U+202A–202E, U+2066–2069),
// zero-width characters (U+200B–200F), BOM (U+FEFF)… They can make "evil<U+202E>fdp.exe"
// look like "evilexe.pdf" or hide characters entirely.
const INVISIBLE = /[\p{Cc}\p{Cf}]/gu;

/** Name from the backend (file name, type, extension) safe to display: invisible characters become visible */
export function displayName(s) {
  if (s == null) return '';
  return String(s).replace(
    INVISIBLE,
    (c) => `⟨U+${c.codePointAt(0).toString(16).toUpperCase().padStart(4, '0')}⟩`
  );
}

/** Truncate to `max` characters without splitting surrogate pairs (emoji etc.) */
export function truncate(s, max) {
  const chars = Array.from(s ?? '');
  return chars.length > max ? `${chars.slice(0, max - 1).join('')}…` : chars.join('');
}

export const MAX_NAMES = 20;

/**
 * Names of a file node, capped by the backend (at most MAX_NAMES + `names_total`):
 * { shown, more } where `more` = how many names were not sent. Works without `names_total`.
 */
export function cappedNames(node) {
  const all = Array.isArray(node?.names) ? node.names : [];
  const shown = all.slice(0, MAX_NAMES);
  const total = Number.isFinite(node?.names_total) ? Math.max(node.names_total, all.length) : all.length;
  return { shown, more: total - shown.length };
}

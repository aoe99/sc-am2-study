// Preferences live in localStorage: small, synchronous, and safe to lose.
// Anything worth keeping (answers, Leitner boxes) goes to IndexedDB instead.

const KEY = 'sc-am2:settings';

const DEFAULTS = {
  theme: 'auto',          // auto | light | dark
  fontScale: 1,           // 0.9 | 1 | 1.15
  shuffleChoices: true,   // §5-5 — on by default
  mergeDuplicates: true,  // §5-6 — count a re-used question once
  grading: 'immediate',   // immediate | end
};

let cache = null;

export function all() {
  if (cache) return cache;
  try {
    cache = { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) || '{}') };
  } catch {
    cache = { ...DEFAULTS };
  }
  return cache;
}

export const get = k => all()[k];

export function set(k, v) {
  const s = all();
  s[k] = v;
  try { localStorage.setItem(KEY, JSON.stringify(s)); } catch { /* private mode */ }
  applyChrome();
  return v;
}

export function replaceAll(obj) {
  cache = { ...DEFAULTS, ...obj };
  try { localStorage.setItem(KEY, JSON.stringify(cache)); } catch { /* ignore */ }
  applyChrome();
}

/** Push theme and text size onto the document root. */
export function applyChrome() {
  const s = all();
  const root = document.documentElement;
  root.dataset.theme = s.theme;
  root.style.setProperty('--font-scale', String(s.fontScale));
}

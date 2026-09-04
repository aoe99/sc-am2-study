// Router and boot. Hash routes keep the back button working inside the PWA.

import * as settings from './settings.js';
import * as data from './data.js';
import { $, clear, el, toast } from './ui.js';

import renderHome from './views/home.js';
import renderSetup from './views/setup.js';
import renderQuiz from './views/quiz.js';
import renderResult from './views/result.js';
import renderStats from './views/stats.js';
import renderSettings from './views/settings.js';
import renderImport from './views/import.js';

const routes = {
  home: renderHome,
  setup: renderSetup,
  quiz: renderQuiz,
  result: renderResult,
  stats: renderStats,
  settings: renderSettings,
  import: renderImport,
};

export function go(path) {
  if (location.hash === '#/' + path) render();
  else location.hash = '#/' + path;
}

export const ctx = {
  run: null,          // the quiz currently being answered
  lastResult: null,   // finished run, for the result screen
};

function parse() {
  const raw = (location.hash || '#/home').replace(/^#\//, '');
  const [name, ...rest] = raw.split('/');
  return { name: routes[name] ? name : 'home', args: rest };
}

let cleanup = null;

async function render() {
  const { name, args } = parse();
  const view = $('#view');
  const extra = $('#bar-extra');
  if (cleanup) { try { cleanup(); } catch { /* ignore */ } cleanup = null; }
  clear(extra);

  if (!data.isLoaded() && name !== 'import' && name !== 'settings') {
    go('import');
    return;
  }
  clear(view);
  try {
    cleanup = await routes[name]({ view, extra, args, go, ctx }) || null;
  } catch (err) {
    console.error(err);
    clear(view).append(
      el('div', { class: 'card' },
        el('h2', { text: '表示できませんでした' }),
        el('p', { class: 'muted', text: String(err && err.message || err) }),
        el('button', { class: 'primary', onclick: () => go('home') }, 'ホームへ')));
  }
  document.scrollingElement.scrollTop = 0;
}

window.addEventListener('hashchange', render);

/** Leaving mid-exam by accident would be unrecoverable — warn first.
 *  午後 is written back to IndexedDB as it goes, so it survives a reload; the
 *  warning is still worth showing because the clock does not stop. */
window.addEventListener('beforeunload', e => {
  if (ctx.run && ctx.run.deadline && !ctx.run.finished) {
    e.preventDefault();
    e.returnValue = '';
  }
});

async function boot() {
  settings.applyChrome();
  await data.load();
  await render();
  if ('serviceWorker' in navigator && location.protocol !== 'file:') {
    try {
      const reg = await navigator.serviceWorker.register('sw.js');
      reg.update().catch(() => {});
      let reloading = false;
      navigator.serviceWorker.addEventListener('controllerchange', () => {
        // A newer build has taken over; reload so the page actually runs it.
        // Not mid-exam though — losing the sitting costs more than the wait.
        if (reloading || (ctx.run && !ctx.run.finished)) return;
        reloading = true;
        location.reload();
      });
    } catch { /* offline support is a bonus, not a requirement */ }
  }
}

boot().catch(err => {
  console.error(err);
  $('#view').append(el('p', { class: 'muted', text: '起動に失敗しました: ' + err.message }));
});

export { toast };

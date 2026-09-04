// First-run screen: take the data file from the user's own storage.
// The corpus is copyrighted, so it is never served with the app (§5-2).

import * as data from '../data.js';
import { el, clear, toast, fmtDate } from '../ui.js';

export default async function renderImport({ view, go }) {
  const loaded = data.isLoaded();
  const meta = data.meta();

  const status = el('p', { class: 'muted' });
  const picker = el('input', {
    type: 'file', accept: '.json,.bin,application/json', id: 'packfile',
    multiple: true,
    onchange: ev => ev.target.files.length && start([...ev.target.files]),
  });

  async function start(files) {
    picker.disabled = true;
    // The pair can be picked together or one at a time, in either order; the
    // questions are loaded first so the figures land on a corpus that knows
    // about them.
    files.sort((a, b) => (a.name.endsWith('.bin') ? 1 : 0)
                       - (b.name.endsWith('.bin') ? 1 : 0));
    const done = [];
    try {
      for (const f of files) {
        const info = await data.importPack(f, msg => {
          status.textContent = `${f.name}: ${msg}`;
        });
        done.push(info.figureCount != null && info.questionCount == null
          ? `図表 ${info.figureCount} 枚`
          : `${info.questionCount ?? 0} 問`);
      }
      toast(done.join(' / ') + ' を読み込みました');
      go('home');
    } catch (err) {
      status.textContent = '';
      toast(err.message, 'err');
      picker.disabled = false;
    }
  }

  view.append(
    el('div', { class: 'card' },
      el('h2', { text: loaded ? '問題データの追加・入れ替え' : '問題データの読み込み' }),
      loaded
        ? el('div', {},
            el('p', { class: 'muted' },
              `現在 ${data.questions().length} 問 / ${data.sessions().length} 回`
              + (meta && meta.importedAt ? `（${fmtDate(meta.importedAt)} 読み込み）` : '')),
            el('ul', { class: 'muted' },
              ...data.sections().map(sec => {
                const m = data.metaFor(sec.id) || {};
                return el('li', { text:
                  `${sec.label} ${sec.questionCount}問`
                  + (sec.caseCount ? ` / ${sec.caseCount}事例` : '')
                  + (m.generatedAt
                     ? `  （${String(m.generatedAt).replace('T', ' ').slice(0, 16)}）` : '') });
              })))
        : el('p', {},
            'このアプリには問題データが入っていません。手元の ',
            el('code', { text: 'sc-data-am.json' }), ' と ',
            el('code', { text: 'sc-data-pm.json' }),
            '（および図表の ', el('code', { text: '-figures.bin' }),
            '）を選んでください。まとめて選べます。データはこの端末のブラウザ内にだけ'
            + '保存され、どこにも送信されません。'),
      el('p', {},
        el('label', { class: 'btn primary', for: 'packfile', style: 'display:inline-block' },
          loaded ? '別のファイルを選ぶ' : 'ファイルを選ぶ'),
        picker),
      status,
      loaded && el('p', { class: 'row' },
        el('button', { onclick: () => go('home') }, 'ホームへ'))),

    el('div', { class: 'card' },
      el('h2', { text: 'iPhone で使うには' }),
      el('ol', { class: 'muted' },
        el('li', { text: 'sc-data-am.json / sc-data-pm.json と、その -figures.bin を iCloud Drive に置く' }),
        el('li', { text: 'Safari でこのページを開き、「ファイルを選ぶ」からまとめて読み込む' }),
        el('li', { text: '午前だけ・午後だけを先に入れてもよい。後から足しても既存の学習記録は消えない' }),
        el('li', { text: '共有ボタン →「ホーム画面に追加」でアプリのように使える' })),
      el('p', { class: 'muted' },
        '一度読み込めば次回からは不要です。オフラインでも動きます。'
        + 'ただし Safari の「サイトデータを消去」で消えるので、'
        + '学習記録は設定画面から書き出しておくことをすすめます。')),
  );
  picker.style.display = 'none';
}

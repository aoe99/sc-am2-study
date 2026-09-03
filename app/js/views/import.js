// First-run screen: take the data file from the user's own storage.
// The corpus is copyrighted, so it is never served with the app (§5-2).

import * as data from '../data.js';
import { el, clear, toast, fmtDate } from '../ui.js';

export default async function renderImport({ view, go }) {
  const loaded = data.isLoaded();
  const meta = data.meta();

  const status = el('p', { class: 'muted' });
  const picker = el('input', {
    type: 'file', accept: '.json,application/json', id: 'packfile',
    onchange: ev => ev.target.files[0] && start(ev.target.files[0]),
  });

  async function start(file) {
    picker.disabled = true;
    try {
      const info = await data.importPack(file, msg => { status.textContent = msg; });
      toast(`${info.questionCount ?? data.questions().length} 問を読み込みました`);
      go('home');
    } catch (err) {
      status.textContent = '';
      toast(err.message, 'err');
      picker.disabled = false;
    }
  }

  view.append(
    el('div', { class: 'card' },
      el('h2', { text: loaded ? '問題データの入れ替え' : '問題データの読み込み' }),
      loaded
        ? el('p', { class: 'muted' },
            `現在 ${data.questions().length} 問 / ${data.sessions().length} 回`
            + (meta && meta.importedAt ? `（${fmtDate(meta.importedAt)} 読み込み）` : ''))
        : el('p', {},
            'このアプリには問題データが入っていません。手元の ',
            el('code', { text: 'sc-data.json' }),
            ' を選んでください。データはこの端末のブラウザ内にだけ保存され、'
            + 'どこにも送信されません。'),
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
        el('li', { text: 'sc-data.json を iCloud Drive に置く' }),
        el('li', { text: 'Safari でこのページを開き、「ファイルを選ぶ」から読み込む' }),
        el('li', { text: '共有ボタン →「ホーム画面に追加」でアプリのように使える' })),
      el('p', { class: 'muted' },
        '一度読み込めば次回からは不要です。オフラインでも動きます。'
        + 'ただし Safari の「サイトデータを消去」で消えるので、'
        + '学習記録は設定画面から書き出しておくことをすすめます。')),
  );
  picker.style.display = 'none';
}

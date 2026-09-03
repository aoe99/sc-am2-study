// Preferences, plus the manual backup that iOS makes necessary (§5-8).

import * as data from '../data.js';
import * as settings from '../settings.js';
import { el, toast, fmtDate } from '../ui.js';

export default async function renderSettings({ view, go }) {
  const s = settings.all();

  view.append(
    card('表示',
      choiceRow('テーマ', [['auto', 'OSに合わせる'], ['light', 'ライト'], ['dark', 'ダーク']],
        s.theme, v => settings.set('theme', v)),
      choiceRow('文字サイズ', [[0.9, '小'], [1, '標準'], [1.15, '大']],
        s.fontScale, v => settings.set('fontScale', Number(v)))),

    card('出題',
      toggle('選択肢をシャッフルする', s.shuffleChoices, v => settings.set('shuffleChoices', v),
        '記号で答えを覚えてしまうのを防ぎます。解説を開くと元の並びに戻ります。'),
      toggle('再出題を1問にまとめる', s.mergeDuplicates, v => settings.set('mergeDuplicates', v),
        '同じ問題が複数の回に出ている場合、練習・復習では1問として扱います。'
        + '本番モードと年度別モードは常に回ごとの扱いです。')),

    await recordCard(),
    await dataCard(go),

    el('div', { class: 'card row' },
      el('button', { onclick: () => go('home') }, 'ホームへ')),
  );
}

const card = (title, ...kids) =>
  el('div', { class: 'card' }, el('h2', { text: title }), ...kids);

function choiceRow(label, options, current, onPick) {
  const row = el('div', { class: 'chips' });
  for (const [value, text] of options) {
    const c = el('button', {
      class: 'chip', 'aria-pressed': String(String(value) === String(current)),
      onclick: () => {
        [...row.children].forEach(x => x.setAttribute('aria-pressed', String(x === c)));
        onPick(value);
      },
    }, text);
    row.append(c);
  }
  return el('div', { style: 'margin-bottom:14px' },
    el('p', { class: 'muted', style: 'margin:0 0 6px', text: label }), row);
}

function toggle(label, checked, onChange, help) {
  const input = el('input', { type: 'checkbox', onchange: e => onChange(e.target.checked) });
  input.checked = !!checked;
  return el('div', { style: 'margin-bottom:12px' },
    el('label', { class: 'check' }, input, label),
    help ? el('p', { class: 'muted', style: 'margin:0 0 0 30px', text: help }) : null);
}

async function recordCard() {
  const [answers, states] = await Promise.all([data.allAnswers(), data.allStates()]);
  const file = el('input', {
    type: 'file', accept: '.json,application/json', id: 'progressfile',
    style: 'display:none',
    onchange: async ev => {
      const f = ev.target.files[0];
      if (!f) return;
      try {
        const obj = JSON.parse(await f.text());
        const merge = confirm('今の記録に統合しますか？\n\nOK = 統合（新しい方を残す）\nキャンセル = 置き換え');
        const n = await data.importProgress(obj, { merge });
        toast(`解答 ${n.answers} 件を読み込みました`);
        location.reload();
      } catch (err) {
        toast(err.message, 'err');
      }
    },
  });

  return card('学習記録',
    el('p', { class: 'muted', style: 'margin-top:0' },
      `解答 ${(answers || []).length} 件 / 着手 ${(states || []).filter(x => x.attempts).length} 問。`
      + ' iOS は Safari の「サイトデータを消去」で記録が消えます。'
      + '定期的に書き出しておいてください。'),
    el('div', { class: 'row' },
      el('button', { class: 'primary', onclick: doExport }, '書き出す'),
      el('label', { class: 'btn', for: 'progressfile' }, '読み込む'),
      file));
}

async function doExport() {
  const payload = await data.exportProgress(settings.all());
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const name = `sc-shiken-progress-${new Date().toISOString().slice(0, 10)}.json`;
  const a = el('a', { href: url, download: name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
  toast('書き出しました');
}

async function dataCard(go) {
  const meta = data.meta();
  return card('問題データ',
    el('p', { class: 'muted', style: 'margin-top:0' },
      data.isLoaded()
        ? `${data.questions().length} 問 / ${data.sessions().length} 回`
          + (meta && meta.importedAt ? `（${fmtDate(meta.importedAt)} 読み込み）` : '')
          + (meta && meta.assetCount ? ` / 図表 ${meta.assetCount} 枚` : '')
        : '未読み込み'),
    el('div', { class: 'row' },
      el('button', { onclick: () => go('import') }, '読み込み / 入れ替え'),
      el('button', {
        onclick: async () => {
          if (!confirm('学習記録をすべて削除します。問題データは残ります。')) return;
          await data.wipeProgress();
          toast('学習記録を削除しました');
          location.reload();
        },
      }, '学習記録を削除')));
}

// Pre-flight for each mode: how many questions, drawn from where.

import * as data from '../data.js';
import * as engine from '../engine.js';
import * as settings from '../settings.js';
import { el, toast } from '../ui.js';

const COUNTS = [10, 25, 50, 0];   // 0 = 全問

export default async function renderSetup({ view, args, go, ctx }) {
  const mode = args[0] || 'practice';
  const section = settings.get('section');
  const states = (await data.allStates()) || [];

  if (mode === 'exam') return examSetup(view, go, ctx, section);
  if (mode === 'review') return start(go, ctx, { mode: 'review' }, states);
  if (mode === 'session') return sessionSetup(view, go, ctx, states, section);

  // --- practice ---
  const chosen = { count: 25, sessionIds: [], tags: [], onlyUnseen: false,
                   onlyWrong: false, onlyReused: false };
  const countRow = el('div', { class: 'chips' });
  COUNTS.forEach(n => {
    const c = el('button', {
      class: 'chip', 'aria-pressed': String(n === chosen.count),
      onclick: () => {
        chosen.count = n;
        [...countRow.children].forEach(x => x.setAttribute('aria-pressed', String(x === c)));
        updateCount();
      },
    }, n === 0 ? '全問' : `${n}問`);
    countRow.append(c);
  });

  const sessionRow = el('div', { class: 'chips' });
  for (const s of data.sessionsIn(section)) {
    sessionRow.append(toggleChip(s.label.replace(/年度\s*/, ''), on => {
      if (on) chosen.sessionIds.push(s.id);
      else chosen.sessionIds = chosen.sessionIds.filter(x => x !== s.id);
      updateCount();
    }));
  }

  const tagRow = el('div', { class: 'chips' });
  for (const t of data.allTags(section)) {
    tagRow.append(toggleChip(t, on => {
      if (on) chosen.tags.push(t);
      else chosen.tags = chosen.tags.filter(x => x !== t);
      updateCount();
    }));
  }

  const unseen = el('input', { type: 'checkbox', onchange: e => { chosen.onlyUnseen = e.target.checked; updateCount(); } });
  const wrong = el('input', { type: 'checkbox', onchange: e => { chosen.onlyWrong = e.target.checked; updateCount(); } });
  const reused = el('input', { type: 'checkbox', onchange: e => { chosen.onlyReused = e.target.checked; updateCount(); } });
  const grading = el('select', {},
    el('option', { value: 'immediate' }, '1問ごとに即時判定'),
    el('option', { value: 'end' }, '最後にまとめて採点'));
  grading.value = settings.get('grading');

  const available = el('p', { class: 'muted' });
  const startBtn = el('button', { class: 'primary', onclick: () => {
    settings.set('grading', grading.value);
    start(go, ctx, { mode: 'practice', section, ...chosen, grading: grading.value }, states);
  } }, '開始');

  function opts() {
    return {
      mode: 'practice', section, ...chosen,
      merge: settings.get('mergeDuplicates'),
    };
  }
  function updateCount() {
    const { list } = engine.build({ ...opts(), count: 0 }, states);
    const n = chosen.count === 0 ? list.length : Math.min(chosen.count, list.length);
    available.textContent = `該当 ${list.length} 問 → ${n} 問を出題`;
    startBtn.disabled = list.length === 0;
  }

  view.append(
    el('div', { class: 'card' }, el('h2', { text: '出題数' }), countRow),
    el('div', { class: 'card' },
      el('h2', { text: '範囲' }),
      el('p', { class: 'muted', style: 'margin:0 0 6px' }, '年度（未選択なら全年度）'),
      sessionRow,
      el('p', { class: 'muted', style: 'margin:14px 0 6px' }, '分野（未選択なら全分野）'),
      tagRow,
      el('div', { style: 'margin-top:10px' },
        el('label', { class: 'check' }, unseen, '未着手のみ'),
        el('label', { class: 'check' }, wrong, '間違えた問題のみ'),
        el('label', { class: 'check' }, reused, '再出題された問題のみ'),
        el('p', { class: 'muted', style: 'margin:0 0 0 30px',
                  text: '過去に2回以上出題された問題に絞る。' }))),
    el('div', { class: 'card' },
      el('h2', { text: '採点方式' }), grading),
    el('div', { class: 'card' }, available, el('div', { class: 'row' }, startBtn,
      el('button', { onclick: () => go('home') }, '戻る'))),
  );
  updateCount();
}

function toggleChip(label, onToggle) {
  const c = el('button', { class: 'chip', 'aria-pressed': 'false', onclick: () => {
    const on = c.getAttribute('aria-pressed') !== 'true';
    c.setAttribute('aria-pressed', String(on));
    onToggle(on);
  } }, label);
  return c;
}

function examSetup(view, go, ctx, section) {
  const info = data.sectionInfo(section);
  view.append(el('div', { class: 'card' },
    el('h2', { text: `本番モード — ${info.label}` }),
    el('ul', { class: 'muted' },
      el('li', { text: `${info.count}問 / ${info.minutes}分。実際の試験と同じ条件` }),
      el('li', { text: '解答中は正誤も解説も出ない。中断・巻き戻しなし' }),
      el('li', { text: `合格ラインは60%（${Math.ceil(info.count * 0.6)}問正解）` }),
      el('li', { text: '再出題された問題も回ごとに別問題として扱う' })),
    el('div', { class: 'row' },
      el('button', { class: 'primary', onclick: async () =>
        start(go, ctx, { mode: 'exam', section },
              (await data.allStates()) || []) }, '開始する'),
      el('button', { onclick: () => go('home') }, '戻る'))));
}

function sessionSetup(view, go, ctx, states, section) {
  const list = el('div', { class: 'grid two' });
  for (const s of data.sessionsIn(section)) {
    list.append(el('button', {
      onclick: () => start(go, ctx, {
        mode: 'session', section, sessionId: s.id, sessionLabel: s.label,
      }, states),
    }, s.label));
  }
  view.append(
    el('div', { class: 'card' }, el('h2', { text: '年度を選ぶ' }), list),
    el('div', { class: 'card' },
      el('button', { onclick: () => go('home') }, '戻る')));
}

function start(go, ctx, opts, states) {
  const merged = {
    section: settings.get('section'),
    merge: settings.get('mergeDuplicates'),
    shuffleChoices: settings.get('shuffleChoices'),
    ...opts,
  };
  const { list } = engine.build(merged, states);
  if (!list.length) {
    toast('該当する問題がありません', 'err');
    go('home');
    return;
  }
  ctx.run = engine.createRun(list, merged);
  go('quiz');
}

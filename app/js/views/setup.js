// Pre-flight for each mode: how many questions, drawn from where.

import * as data from '../data.js';
import * as engine from '../engine.js';
import * as settings from '../settings.js';
import { el, clear, toast } from '../ui.js';

const COUNTS = [10, 25, 50, 0];   // 0 = 全問

export default async function renderSetup({ view, args, go, ctx }) {
  const mode = args[0] || 'practice';
  const section = settings.get('section');
  const states = (await data.allStates()) || [];

  const written = data.isWritten(section);
  if (mode === 'exam') {
    return written ? pmExamSetup(view, go, ctx, states)
                   : examSetup(view, go, ctx, section);
  }
  if (mode === 'review') return start(go, ctx, { mode: 'review' }, states);
  if (mode === 'session' || mode === 'case') {
    return written ? caseSetup(view, go, ctx, states)
                   : sessionSetup(view, go, ctx, states, section);
  }

  // --- practice ---
  const chosen = { count: 25, sessionIds: [], tags: [], kinds: [],
                   onlyUnseen: false, onlyWrong: false, onlyReused: false };
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

  // 午後 mixes 記号選択, 語句 and 記述 in one paper; they are different exercises
  // and worth drilling apart — 記述 is where the time goes.
  const kindRow = el('div', { class: 'chips' });
  if (written) {
    for (const [id, label] of [['choice', '記号選択'], ['term', '語句'], ['essay', '記述']]) {
      kindRow.append(toggleChip(label, on => {
        if (on) chosen.kinds.push(id);
        else chosen.kinds = chosen.kinds.filter(x => x !== id);
        updateCount();
      }));
    }
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
    el('div', { class: 'card' }, el('h2', { text: '出題数' }), countRow,
      written ? el('p', { class: 'muted', style: 'margin:8px 0 0' },
        '設問ごとに出題します。事例本文はいつでも開けます。') : null),
    el('div', { class: 'card' },
      el('h2', { text: '範囲' }),
      el('p', { class: 'muted', style: 'margin:0 0 6px' }, '年度（未選択なら全年度）'),
      sessionRow,
      el('p', { class: 'muted', style: 'margin:14px 0 6px' }, '分野（未選択なら全分野）'),
      tagRow,
      written ? el('p', { class: 'muted', style: 'margin:14px 0 6px' },
                       '解答の種類（未選択なら全種類）') : null,
      written ? kindRow : null,
      el('div', { style: 'margin-top:10px' },
        el('label', { class: 'check' }, unseen, '未着手のみ'),
        el('label', { class: 'check' }, wrong, '間違えた問題のみ'),
        // 午後 is written fresh every sitting; nothing is ever re-set.
        written ? null : el('label', { class: 'check' }, reused, '再出題された問題のみ'),
        written ? null : el('p', { class: 'muted', style: 'margin:0 0 0 30px',
                  text: '過去に2回以上出題された問題に絞る。' }))),
    // 午後 has no key to check against as you go: the 解答例 is read after
    // writing, so marking is always at the end.
    written ? null : el('div', { class: 'card' },
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

/** 事例別: pick one 大問 and answer all of its 設問 in order. */
function caseSetup(view, go, ctx, states) {
  const papers = data.sectionInfo('pm').papers || [];
  const label = id => (papers.find(p => p.id === id) || {}).label || '';
  const bySession = new Map();
  for (const c of data.casesIn('pm')) {
    if (!bySession.has(c.sessionId)) bySession.set(c.sessionId, []);
    bySession.get(c.sessionId).push(c);
  }
  const list = el('div');
  for (const s of data.sessions()) {
    const cs = bySession.get(s.id);
    if (!cs) continue;
    const grid = el('div', { class: 'caselist' });
    for (const c of cs) {
      const n = data.itemsOfCase(c.id).length;
      grid.append(el('button', {
        class: 'caseitem',
        onclick: () => start(go, ctx, {
          mode: 'case', section: 'pm', caseIds: [c.id],
          sessionLabel: `${s.label} ${label(c.paper)} 問${c.no}`,
        }, states),
      },
        el('span', { class: 'casen', text: `${label(c.paper)} 問${c.no}` }),
        el('span', { class: 'casettl', text: c.title }),
        el('span', { class: 'muted', text: `設問${n}` })));
    }
    list.append(el('div', { class: 'card' }, el('h2', { text: s.label }), grid));
  }
  if (!list.children.length)
    list.append(el('div', { class: 'card' },
      el('p', { class: 'muted', text: '午後のデータが読み込まれていません。' })));
  view.append(list, el('div', { class: 'card' },
    el('button', { onclick: () => go('home') }, '戻る')));
}

/** 本番: one sitting's paper, its own clock, and its own 選択 rule. */
function pmExamSetup(view, go, ctx, states) {
  const papers = data.sectionInfo('pm').papers || [];
  const sessions = data.sessions().filter(s =>
    data.casesIn('pm').some(c => c.sessionId === s.id));
  const chosen = { sessionId: (sessions[sessions.length - 1] || {}).id, paper: null,
                   caseIds: [] };

  const sessSel = el('select', { onchange: e => { chosen.sessionId = e.target.value; redraw(); } },
    ...sessions.map(s => el('option', { value: s.id }, s.label)));
  sessSel.value = chosen.sessionId || '';
  const paperRow = el('div', { class: 'chips' });
  const caseBox = el('div');
  const rules = el('ul', { class: 'muted' });
  const startBtn = el('button', { class: 'primary' }, '開始する');

  function papersOf() {
    const ids = [...new Set(data.casesIn('pm')
      .filter(c => c.sessionId === chosen.sessionId).map(c => c.paper))];
    return papers.filter(p => ids.includes(p.id));
  }

  function redraw() {
    const ps = papersOf();
    if (!ps.some(p => p.id === chosen.paper)) chosen.paper = (ps[0] || {}).id;
    const cfg = engine.examConfig('pm', chosen.paper);
    chosen.caseIds = [];

    clear(paperRow);
    for (const p of ps) {
      paperRow.append(el('button', {
        class: 'chip', 'aria-pressed': String(p.id === chosen.paper),
        onclick: () => { chosen.paper = p.id; redraw(); },
      }, p.label));
    }
    clear(rules);
    rules.append(
      el('li', { text: `${cfg.cases}問中${cfg.choose}問を選択 / ${cfg.minutes}分` }),
      el('li', { text: '解答中は解答例も解説も出ない。書き終えてから採点する' }),
      el('li', { text: '合格ラインは60%。△は0.5問として数える' }),
      el('li', { text: '時計は止まらない。中断してもここまでは残る' }));

    clear(caseBox);
    const cs = data.casesIn('pm').filter(c =>
      c.sessionId === chosen.sessionId && c.paper === chosen.paper);
    for (const c of cs) {
      const box = el('input', {
        type: 'checkbox',
        onchange: e => {
          if (e.target.checked) chosen.caseIds.push(c.id);
          else chosen.caseIds = chosen.caseIds.filter(x => x !== c.id);
          // The real paper lets you circle exactly two; more are not marked.
          for (const b of caseBox.querySelectorAll('input'))
            b.disabled = !b.checked && chosen.caseIds.length >= cfg.choose;
          startBtn.disabled = chosen.caseIds.length !== cfg.choose;
        },
      });
      caseBox.append(el('label', { class: 'check' }, box,
        `問${c.no}  ${c.title}（設問${data.itemsOfCase(c.id).length}）`));
    }
    startBtn.disabled = true;
  }

  startBtn.addEventListener('click', () => {
    const cfg = engine.examConfig('pm', chosen.paper);
    const sess = data.sessions().find(s => s.id === chosen.sessionId);
    start(go, ctx, {
      mode: 'exam', section: 'pm', paper: chosen.paper, minutes: cfg.minutes,
      caseIds: chosen.caseIds,
      sessionLabel: `${sess ? sess.label : ''} ${(papers.find(p => p.id === chosen.paper) || {}).label || ''}`,
    }, states);
  });

  view.append(
    el('div', { class: 'card' }, el('h2', { text: '本番モード — 午後' }),
      el('p', { class: 'muted', style: 'margin:0 0 6px' }, '回'), sessSel,
      el('p', { class: 'muted', style: 'margin:14px 0 6px' }, '区分'), paperRow,
      rules),
    el('div', { class: 'card' }, el('h2', { text: '解く問題を選ぶ' }), caseBox),
    el('div', { class: 'card row' }, startBtn,
      el('button', { onclick: () => go('home') }, '戻る')));
  redraw();
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
  data.saveRun(ctx.run);
  go('quiz');
}

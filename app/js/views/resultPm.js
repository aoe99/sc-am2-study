// 午後の結果画面。書いたものを解答例と並べ、ここでも採点し直せる。
//
// 本番モード was answered without ever seeing a 解答例, so most of the marking
// happens here — write for 150 minutes, then go through the paper the way you
// would with the 採点講評 open beside you. Re-marking a 設問 replaces its verdict
// rather than adding an attempt: changing your mind about your own answer is
// not a second attempt at it.

import * as data from '../data.js';
import * as engine from '../engine.js';
import { el, pct, fmtClock, paras } from '../ui.js';
import { figure } from '../figures.js';

const MARKS = [
  { value: true, label: '○', cls: 'ok' },
  { value: engine.PARTIAL, label: '△', cls: 'partial' },
  { value: false, label: '×', cls: 'ng' },
];

export default async function renderResultPm({ view, extra, go, ctx }) {
  const run = ctx.lastResult;
  const states = new Map(((await data.allStates()) || []).map(s => [s.questionId, s]));

  // Anything decidable by string comparison is settled without being asked:
  // 記号 and 語句 have one right answer and the reader gains nothing by
  // confirming it forty times. A 設問 left blank is not settled at all — 午前
  // does not record an unanswered question either, and dropping every 設問 you
  // never reached into box 1 would bury the ones you actually got wrong.
  if (!run.settled) {
    for (const item of run.items) {
      if (item.result !== null) continue;
      if (!(item.typed || []).some(t => t && t.trim())) continue;
      const q = data.byId(item.id);
      const auto = engine.autoResult(q, item.typed);
      if (auto === null) continue;
      const { state, answer } = engine.grade(run, item, auto, states.get(item.id));
      states.set(item.id, state);
      await data.putState(state);
      await data.addAnswer(answer);
    }
    run.settled = true;
  }

  extra.append(el('button', { class: 'icon ghost', onclick: () => go('home') }, 'ホーム'));

  const head = el('div', { class: 'card' });
  const list = el('div', { class: 'card' });
  view.append(head, list);

  async function mark(item, value) {
    const { state, answer } = engine.grade(run, item, value, states.get(item.id));
    states.set(item.id, state);
    await data.putState(state);
    await data.addAnswer(answer);
    drawHead();
    drawRow(item);
  }

  function drawHead() {
    const total = run.items.length;
    const ok = engine.scoreOf(run);
    const half = engine.partialCount(run);
    const unmarked = total - engine.markedCount(run);
    const ratio = Math.round(engine.scoreRatio(run) * 100);
    const passed = engine.passed(run);
    const isExam = run.mode === 'exam';
    const elapsed = (run.endedAt || Date.now()) - run.startedAt;

    head.replaceChildren(
      el('h2', { text: (isExam ? '本番モードの結果' : '結果') + ' — 午後'
                       + (run.sessionLabel ? `  ${run.sessionLabel}` : '') }),
      el('div', { class: 'grid two' },
        stat(`${ok} / ${total}`, '○（正解）'),
        stat(String(half), '△（一部）'),
        stat(ratio + '%', '得点率（△は0.5）'),
        stat(fmtClock(elapsed), '所要時間'),
        isExam ? el('div', { class: 'stat' },
          el('b', { text: passed ? '合格' : '不合格',
                    style: `color:var(--${passed ? 'ok' : 'ng'})` }),
          el('span', { text: '合格ライン 60%' })) : null,
        unmarked ? stat(String(unmarked), '未採点') : null),
      el('div', { style: 'margin-top:14px' },
        el('div', { class: 'bar-track' },
          el('div', { class: 'bar-fill',
                      style: `width:${ratio}%;background:var(--${passed ? 'ok' : 'ng'})` }))),
      unmarked ? el('p', { class: 'muted', style: 'margin:10px 0 0' },
        `記述 ${unmarked}問 が未採点です。下の一覧で ○ / △ / × を選ぶと学習記録に残ります。`) : null,
      caseTable(run));
  }

  const rowNodes = new Map();
  function drawRow(item) {
    const node = rowNodes.get(item.id);
    if (node) node.replaceChildren(...rowChildren(item));
  }

  function rowChildren(item) {
    const q = data.byId(item.id);
    const c = data.caseOf(q);
    const parts = q.parts && q.parts.length ? q.parts : [];
    const mark7 = item.result === true ? '○'
      : item.result === engine.PARTIAL ? '△'
      : item.result === false ? '×' : '—';
    const cls = item.result === true ? 'ok'
      : item.result === engine.PARTIAL ? 'partial'
      : item.result === false ? 'ng' : 'muted';

    const detail = el('div', { style: 'padding:6px 0 10px' });
    detail.append(el('div', { class: 'qtext' },
      q.lead ? el('p', { class: 'lead', text: q.lead }) : null,
      ...paras(q.text)));
    const table = el('div', { class: 'keytable' });
    parts.forEach((p, i) => {
      const mine = ((item.typed || [])[i] || '').trim();
      const hit = engine.autoMark(p, mine);
      table.append(el('div', { class: 'keyrow' + (hit === true ? ' ok' : hit === false ? ' ng' : '') },
        el('span', { class: 'blank', text: p.label || (parts.length > 1 ? `${i + 1}` : '解答') }),
        el('div', {},
          el('p', { class: 'mine', text: mine || '（未記入）' }),
          el('p', { class: 'key', text: p.answer }),
          ...(p.options || []).slice(1).map(o =>
            el('p', { class: 'key alt', text: '別解: ' + o })))));
    });
    detail.append(table);
    // IPA comments only on the 設問 that went badly; the 大問's own paragraph
    // stands in for the rest.
    const note = q.commentary || (c && c.overview) || '';
    if (note) {
      detail.append(
        el('h3', { text: q.commentary ? '採点講評' : '採点講評（この大問の全体）' }),
        el('div', { class: 'commentary' }, ...paras(note)));
    }
    if (q.explanation) {
      detail.append(el('details', { class: 'explain-fold' },
        el('summary', { text: `解説（設問${q.setsu}）` }),
        el('div', { class: 'explain' }, ...paras(q.explanation),
          el('div', { class: 'src', text: '出典: ' + (q.explanationSource || '教科書解説') }))));
    }
    const marks = el('div', { class: 'marks' });
    for (const m of MARKS) {
      marks.append(el('button', {
        class: 'mark ' + m.cls, 'aria-pressed': String(item.result === m.value),
        onclick: () => mark(item, m.value),
      }, m.label));
    }
    detail.append(el('h3', { text: '自己採点' }), marks);

    return [
      el('summary', { style: 'cursor:pointer;min-height:44px;display:flex;gap:10px;align-items:center' },
        el('span', { class: cls, style: 'font-weight:700', text: mark7 }),
        el('span', { style: 'flex:1;min-width:0' },
          el('span', { class: 'muted', text: `${c ? '問' + c.no + ' ' : ''}${q.label}  ` }),
          (q.text || '').slice(0, 40) + ((q.text || '').length > 40 ? '…' : '')),
        q.commentaryRate
          ? el('span', { class: 'chip rate rate-' + rateClass(q.commentaryRate),
                         text: q.commentaryRate }) : null),
      detail,
    ];
  }

  function caseTable(run) {
    const by = new Map();
    for (const item of run.items) {
      const q = data.byId(item.id);
      const cur = by.get(q.caseId) || { n: 0, s: 0 };
      cur.n += 1;
      cur.s += item.result === true ? 1 : item.result === engine.PARTIAL ? 0.5 : 0;
      by.set(q.caseId, cur);
    }
    if (by.size < 2) return null;
    const rows = [...by.entries()].map(([id, v]) => {
      const c = data.caseById(id);
      return el('tr', {},
        el('td', { text: c ? `問${c.no} ${c.title}` : id }),
        el('td', { class: 'num', text: `${v.s} / ${v.n}` }),
        el('td', { class: 'num', text: pct(v.s, v.n) + '%' }));
    });
    return el('div', { class: 'scroll-x', style: 'margin-top:14px' },
      el('table', { class: 'plain' },
        el('thead', {}, el('tr', {},
          el('th', { text: '事例' }), el('th', { class: 'num', text: '得点' }),
          el('th', { class: 'num', text: '率' }))),
        el('tbody', {}, ...rows)));
  }

  drawHead();
  list.append(el('h2', { text: `設問 ${run.items.length}問` }));
  // Unmarked 記述 first: they are the only rows that still need the reader.
  const order = [...run.items].sort((a, b) =>
    (a.result === null ? 0 : 1) - (b.result === null ? 0 : 1));
  for (const item of order) {
    const node = el('details', { style: 'border-top:1px solid var(--line);padding:8px 0',
                                 open: item.result === null });
    node.replaceChildren(...rowChildren(item));
    rowNodes.set(item.id, node);
    list.append(node);
  }

  // Figures for every 事例 the run touched, so the answers can be checked
  // against the drawing without going back to the question screen.
  const seen = new Set(run.items.map(i => (data.byId(i.id) || {}).caseId));
  const figs = el('div', { class: 'card' });
  for (const id of seen) {
    const c = data.caseById(id);
    for (const f of (c && c.figures) || [])
      figs.append(await figure(typeof f === 'string' ? f : f.file));
  }
  if (figs.children.length) {
    figs.prepend(el('h2', { text: '図表' }));
    view.append(figs);
  }

  view.append(el('div', { class: 'card row' },
    el('button', { class: 'primary', onclick: () => go('home') }, 'ホームへ'),
    el('button', { onclick: () => go('stats') }, '統計を見る')));
}

const stat = (value, label) =>
  el('div', { class: 'stat' }, el('b', { text: String(value) }),
     el('span', { text: label }));

const rateClass = r => ({ '高': 'hi', 'やや高': 'hi', '平均': 'mid',
                          'やや低': 'lo', '低': 'lo' })[r] || 'mid';

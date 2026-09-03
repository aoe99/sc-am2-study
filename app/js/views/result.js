// Score sheet. Also the grading pass for 「最後にまとめて採点」 and 本番モード.

import * as data from '../data.js';
import * as engine from '../engine.js';
import { el, pct, fmtClock, paras } from '../ui.js';
import { explanation, figure, figureImg } from './quiz.js';

export default async function renderResult({ view, extra, go, ctx }) {
  const run = ctx.lastResult;
  if (!run) { go('home'); return; }

  // In 「まとめて採点」 the answers were held back; settle them all now.
  if (run.grading === 'end' && !run.settled) {
    const states = new Map(((await data.allStates()) || []).map(s => [s.questionId, s]));
    for (const item of run.items) {
      if (item.selected === null) { item.correct = false; continue; }
      if (item.correct === null) {
        const { state, answer } = engine.grade(run, item, item.selected, states.get(item.id));
        await data.putState(state);
        await data.addAnswer(answer);
      }
    }
    run.settled = true;
  }

  const total = run.items.length;
  const score = engine.scoreOf(run);
  const ratio = pct(score, total);
  const isExam = run.mode === 'exam';
  const ok = score / total >= engine.PASS_RATIO;
  const elapsed = (run.endedAt || Date.now()) - run.startedAt;

  extra.append(el('button', { class: 'icon ghost', onclick: () => go('home') }, 'ホーム'));

  const secLabel = run.section ? data.sectionInfo(run.section).label : '';
  view.append(el('div', { class: 'card' },
    el('h2', { text: (isExam ? '本番モードの結果' : '結果')
                     + (secLabel ? ` — ${secLabel}` : '') }),
    el('div', { class: 'grid two' },
      el('div', { class: 'stat' },
        el('b', { text: `${score} / ${total}` }), el('span', { text: '正解数' })),
      el('div', { class: 'stat' },
        el('b', { text: ratio + '%' }), el('span', { text: '正答率' })),
      el('div', { class: 'stat' },
        el('b', { text: fmtClock(elapsed) }), el('span', { text: '所要時間' })),
      isExam ? el('div', { class: 'stat' },
        el('b', { text: ok ? '合格' : '不合格', style: `color:var(--${ok ? 'ok' : 'ng'})` }),
        el('span', { text: `合格ライン 60%（${Math.ceil(total * engine.PASS_RATIO)}問）` })) : null),
    el('div', { style: 'margin-top:14px' },
      el('div', { class: 'bar-track' },
        el('div', { class: 'bar-fill', style: `width:${ratio}%;background:var(--${ok ? 'ok' : 'ng'})` })))));

  // Per-tag breakdown.
  const tally = new Map();
  for (const item of run.items) {
    const q = data.byId(item.id);
    for (const t of q.tags || []) {
      const cur = tally.get(t) || { n: 0, c: 0 };
      cur.n += 1; if (item.correct) cur.c += 1;
      tally.set(t, cur);
    }
  }
  if (tally.size) {
    const rows = [...tally.entries()].sort((a, b) => b[1].n - a[1].n).map(([t, v]) =>
      el('tr', {},
        el('td', { text: t }),
        el('td', { class: 'num', text: `${v.c}/${v.n}` }),
        el('td', { class: 'num', text: pct(v.c, v.n) + '%' })));
    view.append(el('div', { class: 'card' },
      el('h2', { text: '分野別' }),
      el('div', { class: 'scroll-x' },
        el('table', { class: 'plain' },
          el('thead', {}, el('tr', {},
            el('th', { text: '分野' }),
            el('th', { class: 'num', text: '正解' }),
            el('th', { class: 'num', text: '率' }))),
          el('tbody', {}, ...rows)))));
  }

  const wrong = run.items.filter(i => !i.correct);
  const listCard = el('div', { class: 'card' },
    el('h2', { text: wrong.length ? `間違えた問題 ${wrong.length}問` : '全問正解' }));
  for (const item of (wrong.length ? wrong : run.items)) {
    listCard.append(await resultRow(item, run));
  }
  view.append(listCard);

  if (wrong.length && wrong.length < run.items.length) {
    view.append(el('div', { class: 'card' },
      el('h2', { text: '全問を見る' }),
      ...await Promise.all(run.items.filter(i => i.correct).map(i => resultRow(i, run)))));
  }

  view.append(el('div', { class: 'card row' },
    el('button', { class: 'primary', onclick: () => go('home') }, 'ホームへ'),
    el('button', { onclick: () => go('stats') }, '統計を見る')));
}

async function resultRow(item, run) {
  const q = data.byId(item.id);
  const sess = data.sessions().find(s => s.id === q.sessionId);
  const wrap = el('details', { style: 'border-top:1px solid var(--line);padding:8px 0' });
  const mark = item.correct ? '○' : (item.selected === null ? '—' : '×');
  const group = data.groupOf(q);
  wrap.append(el('summary', { style: 'cursor:pointer;min-height:44px;display:flex;gap:10px;align-items:center' },
    el('span', { style: `font-weight:700;color:var(--${item.correct ? 'ok' : 'ng'})`, text: mark }),
    el('span', { style: 'flex:1;min-width:0' },
      group.length > 1
        ? el('span', { class: 'chip reuse', style: 'margin-right:6px',
                       text: `${group.length}回` }) : null,
      el('span', { class: 'muted', text: sess ? `${sess.label} 問${q.no}  ` : '' }),
      q.text.slice(0, 46) + (q.text.length > 46 ? '…' : ''))));

  const detail = el('div', { style: 'padding:6px 0 10px' });
  detail.append(el('div', { class: 'qtext' }, ...paras(q.text)));
  for (const f of q.figures || []) detail.append(await figure(f));
  const ol = el('ol', { class: 'choices' });
  for (const c of q.choices) {
    const cf = (q.choiceFigures || {})[c.key];
    let cls = 'choice' + (cf ? ' has-figure' : '');
    if (c.key === q.answer) cls += ' correct';
    else if (c.key === item.selected) cls += ' wrong';
    const bodyNode = el('span', { class: 'body' });
    if (cf) bodyNode.append(await figureImg(cf));
    else if (q.choicesInFigure)
      bodyNode.append(el('span', { class: 'muted', text: '上の図から選ぶ' }));
    else bodyNode.textContent = c.text;
    ol.append(el('li', {}, el('div', { class: cls },
      el('span', { class: 'key', text: c.key }), bodyNode)));
  }
  detail.append(ol);
  detail.append(el('p', { class: 'muted', style: 'margin:10px 0 0' },
    item.selected === null ? '無解答' : `あなたの解答: ${item.selected}  /  正解: ${q.answer}`));
  detail.append(explanation(q));
  wrap.append(detail);
  return wrap;
}

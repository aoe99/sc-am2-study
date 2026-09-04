// Landing screen: what to do next, and how it has been going.

import * as data from '../data.js';
import * as leitner from '../leitner.js';
import * as settings from '../settings.js';
import { el, pct, fmtDate } from '../ui.js';

const DAY = 86400000;

export default async function renderHome({ view, extra, go, ctx }) {
  const secs = data.sections();
  let section = settings.get('section');
  if (!secs.some(s => s.id === section)) section = settings.set('section', secs[0].id);
  const info = data.sectionInfo(section);
  const written = data.isWritten(section);
  const qs = data.inSection(section);
  // Everything on this screen sits under the 午前Ⅰ/午前Ⅱ switch, so the record
  // has to be narrowed to the paper being shown — otherwise the counts read as
  // the same number whichever tab is selected.
  const mine = new Set(qs.map(q => q.id));
  const states = ((await data.allStates()) || []).filter(s => mine.has(s.questionId));
  const answers = ((await data.allAnswers()) || []).filter(a => mine.has(a.questionId));
  const byId = new Map(states.map(s => [s.questionId, s]));

  const attempted = states.filter(s => s.attempts > 0);
  const totalAttempts = attempted.reduce((n, s) => n + s.attempts, 0);
  const totalCorrect = attempted.reduce((n, s) => n + s.corrects, 0);
  const now = Date.now();
  const due = qs.filter(q => leitner.isDue(byId.get(q.id), now)).length;

  const since = now - 7 * DAY;
  const week = answers.filter(a => a.answeredAt >= since);
  const perDay = new Array(7).fill(0);
  for (const a of week) {
    const d = Math.floor((now - a.answeredAt) / DAY);
    if (d >= 0 && d < 7) perDay[6 - d] += 1;
  }

  extra.append(
    el('button', { class: 'icon ghost', onclick: () => go('stats') }, '統計'),
    el('button', { class: 'icon ghost', onclick: () => go('settings') }, '設定'));

  if (secs.length > 1) {
    const row = el('div', { class: 'chips', style: 'margin-bottom:14px' });
    for (const s of secs) {
      row.append(el('button', {
        class: 'chip', 'aria-pressed': String(s.id === section),
        onclick: () => { settings.set('section', s.id); go('home'); },
      }, `${s.label}  ${s.questionCount}問`));
    }
    view.append(row);
  }

  // A 午後 sitting is 150 minutes; it will be interrupted. The run is written
  // back as it is answered, so the way back into it belongs here.
  const saved = ctx ? await data.loadRun() : null;
  // 午前 counts a chosen key, 午後 a written answer or a mark. A run with none
  // of those has nothing to resume — and leaving one on screen is what showed
  // "中断した学習 0問" for good after any finished sitting.
  const doneOf = r => (r.items || []).filter(i =>
    i.result !== null || i.selected != null
    || (i.typed || []).some(t => t && t.trim())).length;
  const worthResuming = saved && !saved.finished && saved.items && saved.items.length
    && (doneOf(saved) > 0 || saved.deadline);
  if (saved && !worthResuming) await data.clearRun();
  if (worthResuming) {
    const done = doneOf(saved);
    const secInfo = data.sectionInfo(saved.section);
    view.append(el('div', { class: 'card resume' },
      el('h2', { text: '中断した学習があります' }),
      el('p', { class: 'muted' },
        `${secInfo ? secInfo.label : ''}${saved.sessionLabel ? ' ' + saved.sessionLabel : ''}`
        + `  ${done} / ${saved.items.length}問  `
        + `（${fmtDate(saved.savedAt || saved.startedAt)}）`),
      saved.deadline && saved.deadline < Date.now()
        ? el('p', { class: 'muted', text: '制限時間は過ぎています。再開すると結果画面に進みます。' }) : null,
      el('div', { class: 'row' },
        el('button', { class: 'primary', onclick: () => {
          if (saved.section) settings.set('section', saved.section);
          ctx.run = saved;
          go('quiz');
        } }, '再開する'),
        el('button', { onclick: async () => { await data.clearRun(); go('home'); } },
          '破棄する'))));
  }

  view.append(
    el('div', { class: 'card' },
      el('div', { class: 'grid two' },
        stat(qs.length, written ? '設問数' : '問題数'),
        stat(attempted.length, '着手'),
        stat(pct(totalCorrect, totalAttempts) + '%', '全体正解率'),
        stat(due, '今日の復習')),
      el('div', { style: 'margin-top:14px' },
        el('div', { class: 'bar-track' },
          el('div', { class: 'bar-fill', style: `width:${pct(attempted.length, qs.length)}%` })),
        el('p', { class: 'muted', style: 'margin:6px 0 0' },
          `${attempted.length} / ${qs.length} 問に着手`))),

    el('div', { class: 'card' },
      el('h2', { text: 'モードを選ぶ' }),
      el('div', { class: 'grid two' },
        el('button', { class: 'primary', onclick: () => go('setup/practice') },
          written ? '練習（事例ごと）' : '練習'),
        el('button', { onclick: () => go('setup/exam') },
          written ? `本番 ${examSpan(info)}` : `本番 ${info.count}問${info.minutes}分`),
        el('button', {
          onclick: () => go('setup/review'),
          disabled: due === 0,
        }, due ? `復習 ${due}問` : '復習（なし）'),
        el('button', { onclick: () => go(written ? 'setup/case' : 'setup/session') },
          written ? `事例別 ${data.casesIn(section).length}事例` : '年度別'))),

    el('div', { class: 'card' },
      el('h2', { text: '直近7日' }),
      weekChart(perDay),
      el('p', { class: 'muted', style: 'margin:8px 0 0' },
        week.length ? `${week.length} 問を解答` : 'まだ解答がありません'),
      answers.length ? el('p', { class: 'muted', style: 'margin:2px 0 0' },
        `最終学習: ${fmtDate(Math.max(...answers.map(a => a.answeredAt)))}`) : null),
  );

  // The build stamp of the loaded pack. Keeping it in sight is what tells a
  // stale import apart from a bug in the extraction.
  const meta = data.metaFor(section);
  if (meta && meta.generatedAt) {
    view.append(el('p', { class: 'muted', style: 'text-align:center;font-size:.76rem' },
      `問題データ ${String(meta.generatedAt).replace('T', ' ').slice(0, 16)}`));
  }
}

/** 午後 ran as two papers until 令和5年度秋期; the switch shows both spans. */
function examSpan(info) {
  const mins = [...new Set((info.papers || []).map(p => p.minutes))].sort((a, b) => a - b);
  return mins.length ? mins.join('/') + '分' : `${info.minutes}分`;
}

const stat = (value, label) =>
  el('div', { class: 'stat' }, el('b', { text: String(value) }), el('span', { text: label }));

function weekChart(perDay) {
  const max = Math.max(1, ...perDay);
  const W = 320, H = 72, gap = 8, bw = (W - gap * 6) / 7;
  const labels = ['6日前', '', '', '3日前', '', '', '今日'];
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'chart');
  svg.setAttribute('viewBox', `0 0 ${W} ${H + 16}`);
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', '直近7日の解答数');
  perDay.forEach((n, i) => {
    const x = i * (bw + gap);
    const h = Math.round((n / max) * H);
    svg.append(rect(x, 0, bw, H, 'track'), rect(x, H - h, bw, h, 'fill'));
    if (labels[i]) svg.append(text(x + bw / 2, H + 13, labels[i]));
  });
  return svg;
}

function rect(x, y, w, h, cls) {
  const r = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
  r.setAttribute('x', x); r.setAttribute('y', y);
  r.setAttribute('width', Math.max(0, w)); r.setAttribute('height', Math.max(0, h));
  r.setAttribute('rx', 3); r.setAttribute('class', cls);
  return r;
}

function text(x, y, s) {
  const t = document.createElementNS('http://www.w3.org/2000/svg', 'text');
  t.setAttribute('x', x); t.setAttribute('y', y); t.setAttribute('text-anchor', 'middle');
  t.textContent = s;
  return t;
}

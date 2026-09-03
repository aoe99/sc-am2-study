// Landing screen: what to do next, and how it has been going.

import * as data from '../data.js';
import * as leitner from '../leitner.js';
import * as settings from '../settings.js';
import { el, pct, fmtDate } from '../ui.js';

const DAY = 86400000;

export default async function renderHome({ view, extra, go }) {
  const secs = data.sections();
  let section = settings.get('section');
  if (!secs.some(s => s.id === section)) section = settings.set('section', secs[0].id);
  const info = data.sectionInfo(section);
  const qs = data.inSection(section);
  const states = (await data.allStates()) || [];
  const answers = (await data.allAnswers()) || [];
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

  view.append(
    el('div', { class: 'card' },
      el('div', { class: 'grid two' },
        stat(qs.length, '問題数'),
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
        el('button', { class: 'primary', onclick: () => go('setup/practice') }, '練習'),
        el('button', { onclick: () => go('setup/exam') },
          `本番 ${info.count}問${info.minutes}分`),
        el('button', {
          onclick: () => go('setup/review'),
          disabled: due === 0,
        }, due ? `復習 ${due}問` : '復習（なし）'),
        el('button', { onclick: () => go('setup/session') }, '年度別'))),

    el('div', { class: 'card' },
      el('h2', { text: '直近7日' }),
      weekChart(perDay),
      el('p', { class: 'muted', style: 'margin:8px 0 0' },
        week.length ? `${week.length} 問を解答` : 'まだ解答がありません'),
      answers.length ? el('p', { class: 'muted', style: 'margin:2px 0 0' },
        `最終学習: ${fmtDate(Math.max(...answers.map(a => a.answeredAt)))}`) : null),
  );
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

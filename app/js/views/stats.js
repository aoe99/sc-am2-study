// Progress charts. Hand-drawn SVG — no chart library (§5-7).

import * as data from '../data.js';
import * as leitner from '../leitner.js';
import { el, pct, fmtDate } from '../ui.js';

const SVG = 'http://www.w3.org/2000/svg';
const SESSION_GAP = 20 * 60000;   // a pause this long starts a new sitting

export default async function renderStats({ view, extra, go }) {
  extra.append(el('button', { class: 'icon ghost', onclick: () => go('home') }, 'ホーム'));

  const [answers, states] = await Promise.all([data.allAnswers(), data.allStates()]);
  const rows = (answers || []).slice().sort((a, b) => a.answeredAt - b.answeredAt);
  const byId = new Map((states || []).map(s => [s.questionId, s]));

  if (!rows.length) {
    view.append(el('div', { class: 'card' },
      el('h2', { text: 'まだ記録がありません' }),
      el('p', { class: 'muted', text: '練習モードを一度やると、ここに推移が出ます。' }),
      el('button', { class: 'primary', onclick: () => go('setup/practice') }, '練習を始める')));
    return;
  }

  // --- by tag ---
  const tag = new Map();
  const year = new Map();
  for (const q of data.questions()) {
    const s = byId.get(q.id);
    if (!s || !s.attempts) continue;
    for (const t of q.tags || []) bump(tag, t, s);
    bump(year, q.sessionId, s);
  }

  view.append(barCard('分野別の正解率', [...tag.entries()]
    .sort((a, b) => b[1].n - a[1].n)
    .map(([k, v]) => [k, v.c, v.n])));

  const order = new Map(data.sessions().map((s, i) => [s.id, i]));
  const label = new Map(data.sessions().map(s => [s.id, s.label.replace(/年度\s*/, '')]));
  view.append(barCard('年度別の正解率', [...year.entries()]
    .sort((a, b) => (order.get(a[0]) ?? 0) - (order.get(b[0]) ?? 0))
    .map(([k, v]) => [label.get(k) || k, v.c, v.n])));

  // --- trend over recent sittings ---
  const sittings = [];
  let cur = null;
  for (const a of rows) {
    if (!cur || a.answeredAt - cur.last > SESSION_GAP) {
      cur = { at: a.answeredAt, last: a.answeredAt, n: 0, c: 0 };
      sittings.push(cur);
    }
    cur.last = a.answeredAt;
    cur.n += 1;
    if (a.correct) cur.c += 1;
  }
  const recent = sittings.slice(-30);
  view.append(el('div', { class: 'card' },
    el('h2', { text: `正解率の推移（直近 ${recent.length} セッション）` }),
    lineChart(recent.map(s => pct(s.c, s.n))),
    el('p', { class: 'muted', style: 'margin:8px 0 0' },
      `${fmtDate(recent[0].at)} 〜 ${fmtDate(recent[recent.length - 1].at)}`
      + `  /  全 ${rows.length} 解答`)));

  // --- Leitner ---
  const boxes = leitner.boxCounts(states || []);
  const dueNow = data.questions().filter(q => leitner.isDue(byId.get(q.id))).length;
  view.append(el('div', { class: 'card' },
    el('h2', { text: 'ライトナーの箱' }),
    barChart([1, 2, 3, 4, 5].map(b => [`箱${b}`, boxes[b], Math.max(1, Math.max(...Object.values(boxes)))]), true),
    el('p', { class: 'muted', style: 'margin:8px 0 0' },
      `箱が進むほど再出題の間隔が延びます（当日 / 1日 / 3日 / 7日 / 16日）。`
      + `  今日が期限: ${dueNow} 問`)));
}

function bump(map, key, s) {
  const cur = map.get(key) || { n: 0, c: 0 };
  cur.n += s.attempts;
  cur.c += s.corrects;
  map.set(key, cur);
}

function barCard(title, rows) {
  const card = el('div', { class: 'card' }, el('h2', { text: title }));
  if (!rows.length) {
    card.append(el('p', { class: 'muted', text: 'データがありません' }));
    return card;
  }
  card.append(barChart(rows.map(([k, c, n]) => [k, pct(c, n), 100, `${c}/${n}`])));
  return card;
}

/** Horizontal bars: label, value, max, optional suffix. */
function barChart(rows, rawCount = false) {
  // Tag names run to 12 full-width characters ("ネットワークセキュリティ"),
  // so the label gutter has to be wide enough for them at 11px.
  const rowH = 26, labelW = 148, padR = 48;
  const W = 440, H = rows.length * rowH + 4;
  const svg = document.createElementNS(SVG, 'svg');
  svg.setAttribute('class', 'chart');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('role', 'img');
  rows.forEach(([label, value, max, note], i) => {
    const y = i * rowH + 4;
    const trackW = W - labelW - padR;
    const w = max ? Math.round((value / max) * trackW) : 0;
    svg.append(text(labelW - 6, y + 13, label, 'end'));
    svg.append(rect(labelW, y + 4, trackW, 12, 'track'));
    svg.append(rect(labelW, y + 4, w, 12, 'fill'));
    svg.append(text(W - 4, y + 13, rawCount ? String(value) : (note || value + '%'), 'end'));
  });
  return svg;
}

function lineChart(values) {
  const W = 340, H = 120, padL = 30, padB = 18, padT = 8;
  const svg = document.createElementNS(SVG, 'svg');
  svg.setAttribute('class', 'chart');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', '正解率の推移');
  const plotW = W - padL - 8, plotH = H - padT - padB;
  for (const v of [0, 50, 100]) {
    const y = padT + plotH - (v / 100) * plotH;
    svg.append(line(padL, y, W - 8, y, 'grid'));
    svg.append(text(padL - 5, y + 4, String(v), 'end'));
  }
  const step = values.length > 1 ? plotW / (values.length - 1) : 0;
  const pts = values.map((v, i) => [padL + i * step, padT + plotH - (v / 100) * plotH]);
  if (pts.length > 1) {
    const path = document.createElementNS(SVG, 'path');
    path.setAttribute('class', 'line');
    path.setAttribute('d', pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' '));
    svg.append(path);
  }
  for (const [x, y] of pts) {
    const c = document.createElementNS(SVG, 'circle');
    c.setAttribute('cx', x.toFixed(1)); c.setAttribute('cy', y.toFixed(1));
    c.setAttribute('r', pts.length > 20 ? 1.8 : 2.6);
    c.setAttribute('class', 'dot');
    svg.append(c);
  }
  return svg;
}

function rect(x, y, w, h, cls) {
  const r = document.createElementNS(SVG, 'rect');
  r.setAttribute('x', x); r.setAttribute('y', y);
  r.setAttribute('width', Math.max(0, w)); r.setAttribute('height', h);
  r.setAttribute('rx', 3); r.setAttribute('class', cls);
  return r;
}
function text(x, y, s, anchor = 'start') {
  const t = document.createElementNS(SVG, 'text');
  t.setAttribute('x', x); t.setAttribute('y', y); t.setAttribute('text-anchor', anchor);
  t.textContent = s;
  return t;
}
function line(x1, y1, x2, y2, cls) {
  const l = document.createElementNS(SVG, 'line');
  l.setAttribute('x1', x1); l.setAttribute('y1', y1);
  l.setAttribute('x2', x2); l.setAttribute('y2', y2);
  l.setAttribute('class', cls);
  return l;
}

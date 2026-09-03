// Answering screen. One question at a time.

import * as data from '../data.js';
import * as engine from '../engine.js';
import * as settings from '../settings.js';
import { el, add, clear, shuffled, fmtClock, paras } from '../ui.js';

const KEYS = ['ア', 'イ', 'ウ', 'エ'];
const HOTKEYS = { '1': 0, '2': 1, '3': 2, '4': 3, a: 0, b: 1, c: 2, d: 3 };

export default async function renderQuiz({ view, extra, go, ctx }) {
  const run = ctx.run;
  if (!run) { go('home'); return; }

  const states = new Map(((await data.allStates()) || []).map(s => [s.questionId, s]));
  const body = el('div');
  const nav = el('div', { class: 'navbar' });
  view.append(body, nav);

  let timerId = null;
  if (run.deadline) {
    const clock = el('span', { class: 'timer' });
    extra.append(clock);
    const tick = () => {
      const left = run.deadline - Date.now();     // real time, never a tick count
      clock.textContent = fmtClock(left);
      clock.className = 'timer' + (left <= 0 ? ' danger' : left <= 300000 ? ' warn' : '');
      if (left <= 0) { finish(); }
    };
    tick();
    timerId = setInterval(tick, 500);
    // iOS suspends timers in the background; recompute the moment we return.
    document.addEventListener('visibilitychange', tick);
  } else {
    extra.append(el('button', { class: 'icon ghost', onclick: () => confirmQuit() }, '中断'));
  }

  function confirmQuit() {
    if (engine.answeredCount(run) === 0 || confirm('中断しますか？ ここまでの解答は保存されています。')) {
      ctx.run = null;
      go('home');
    }
  }

  async function choose(item, key) {
    if (item.selected !== null && run.grading === 'immediate') return;
    const prev = states.get(item.id);
    const { state, answer } = engine.grade(run, item, key, prev);
    states.set(item.id, state);
    if (run.mode !== 'exam' || true) {
      await data.putState(state);
      await data.addAnswer(answer);
    }
    draw();
  }

  function next() {
    if (run.index < run.items.length - 1) { run.index += 1; draw(); }
    else finish();
  }

  function prev() {
    if (run.index > 0) { run.index -= 1; draw(); }
  }

  function finish() {
    if (run.finished) return;
    run.finished = true;
    run.endedAt = Date.now();
    if (timerId) clearInterval(timerId);
    ctx.lastResult = run;
    ctx.run = null;
    go('result');
  }

  async function draw() {
    const item = run.items[run.index];
    const q = data.byId(item.id);
    if (!item.shownAt) item.shownAt = Date.now();
    clear(body);
    clear(nav);

    const sess = data.sessions().find(s => s.id === q.sessionId);
    const graded = item.selected !== null && run.grading === 'immediate';
    const reveal = graded && item.revealed;

    body.append(el('div', { class: 'qmeta' },
      el('span', { class: 'no', text: `${run.index + 1} / ${run.items.length}` }),
      run.mode !== 'exam' && sess
        ? el('span', { class: 'chip static', text: `${sess.label} 問${q.no}` }) : null,
      ...(run.mode === 'exam' ? [] : (q.tags || []).map(t =>
        el('span', { class: 'chip static', text: t })))));

    body.append(el('div', { class: 'qtext' }, ...paras(q.text)));
    for (const f of q.figures || []) body.append(await figure(f));

    // §5-5: answering can be shuffled, but the explanation refers to the
    // printed ア/イ/ウ/エ, so revealing it puts the original order back.
    const seed = hash(q.id);
    const shuffledOrder = run.shuffleChoices ? shuffled(KEYS, seed) : KEYS.slice();
    const useShuffle = run.shuffleChoices && !reveal;
    const order = useShuffle ? shuffledOrder : KEYS.slice();
    // Position a key occupied while it was being answered, so the verdict and
    // the annotations always speak in the letters the reader actually saw.
    const shownFor = k => (run.shuffleChoices
      ? KEYS[shuffledOrder.indexOf(k)] : k);

    const list = el('ol', { class: 'choices' });
    for (let i = 0; i < order.length; i++) {
      const key = order[i];
      const choice = q.choices.find(c => c.key === key);
      const shownKey = useShuffle ? KEYS[i] : key;
      let cls = 'choice' + ((q.choiceFigures || {})[key] ? ' has-figure' : '');
      if (graded) {
        if (key === q.answer) cls += ' correct';
        else if (key === item.selected) cls += ' wrong';
      }
      const cfig = (q.choiceFigures || {})[key];
      const bodyNode = el('span', { class: 'body' });
      if (cfig) {
        // The choice is a table row or a 2-D formula; the scan is the choice.
        // Its OCR text is kept in the data for search but is not shown.
        bodyNode.append(await figureImg(cfig));
      } else if (!(choice && choice.text) && q.choicesInFigure) {
        // The four options are one drawing shown above; the buttons just pick.
        bodyNode.append(el('span', { class: 'muted', text: '上の図から選ぶ' }));
      } else {
        bodyNode.textContent = (choice && choice.text) || '';
      }
      if (reveal && run.shuffleChoices && shownFor(key) !== key)
        bodyNode.append(el('span', { class: 'orig', text: `（解答時は ${shownFor(key)}）` }));

      list.append(el('li', {},
        el('button', {
          class: cls, 'aria-pressed': String(item.selected === key),
          onclick: () => choose(item, key),
        },
          el('span', { class: 'key', text: shownKey }),
          bodyNode)));
    }
    body.append(list);

    if (graded) {
      const answerKey = reveal ? q.answer : shownFor(q.answer);
      body.append(el('p', { class: 'verdict ' + (item.correct ? 'ok' : 'ng') },
        item.correct ? '正解' : `不正解 — 正解は ${answerKey}`));
      if (!item.revealed) {
        body.append(el('p', {}, el('button', {
          onclick: () => { item.revealed = true; draw(); },
        }, '解説を見る  （S）')));
      } else {
        body.append(explanation(q));
        body.append(el('p', {}, el('button', {
          class: 'ghost',
          onclick: () => { item.revealed = false; draw(); },
        }, '解説を閉じる')));
      }
    }

    add(nav,
      el('button', { onclick: prev, disabled: run.index === 0 || run.mode === 'exam' }, '前へ'),
      el('span', { class: 'spacer' }),
      run.mode === 'exam'
        ? el('span', { class: 'muted', text: `解答済み ${engine.answeredCount(run)}/${run.items.length}` })
        : null,
      el('button', {
        class: 'primary',
        onclick: next,
        disabled: run.grading === 'immediate' && item.selected === null && run.mode !== 'exam',
      }, run.index === run.items.length - 1 ? '採点する' : '次へ'));
  }

  function onKey(ev) {
    if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
    const item = run.items[run.index];
    const k = ev.key.toLowerCase();
    if (k in HOTKEYS) {
      ev.preventDefault();
      const useShuffle = run.shuffleChoices && !(item.revealed && item.selected !== null);
      const q = data.byId(item.id);
      const order = useShuffle ? shuffled(KEYS, hash(q.id)) : KEYS.slice();
      choose(item, order[HOTKEYS[k]]);
    } else if (ev.key === 'Enter') {
      ev.preventDefault(); next();
    } else if (k === 's' && item.selected !== null && run.grading === 'immediate') {
      ev.preventDefault(); item.revealed = !item.revealed; draw();
    }
  }
  document.addEventListener('keydown', onKey);

  // Swipe left/right to move between questions (§5-10).
  let touchX = null, touchY = null;
  const onStart = e => { touchX = e.changedTouches[0].clientX; touchY = e.changedTouches[0].clientY; };
  const onEnd = e => {
    if (touchX === null) return;
    const dx = e.changedTouches[0].clientX - touchX;
    const dy = e.changedTouches[0].clientY - touchY;
    touchX = null;
    if (Math.abs(dx) < 60 || Math.abs(dx) < Math.abs(dy) * 1.6) return;
    if (dx < 0) next(); else if (run.mode !== 'exam') prev();
  };
  view.addEventListener('touchstart', onStart, { passive: true });
  view.addEventListener('touchend', onEnd, { passive: true });

  await draw();

  return () => {
    if (timerId) clearInterval(timerId);
    document.removeEventListener('keydown', onKey);
  };
}

export function explanation(q) {
  return el('div', { class: 'explain' },
    ...paras(q.explanation),
    el('div', { class: 'src', text: '出典: ' + (q.explanationSource || '教科書解説') }));
}

export async function figure(path) {
  const wrap = el('div', { class: 'figure' });
  wrap.append(await figureImg(path));
  return wrap;
}

export async function figureImg(path) {
  const url = await data.figureUrl(path);
  if (!url) return el('p', { class: 'muted', text: '（図表を読み込めませんでした）' });
  return el('img', {
    src: url, alt: '図表',
    onclick: () => lightbox(url),
  });
}

function lightbox(url) {
  const box = el('div', { class: 'lightbox', onclick: () => box.remove() },
    el('img', { src: url, alt: '図表（拡大）' }));
  document.body.append(box);
}

function hash(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}

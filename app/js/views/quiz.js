// Answering screen. One question at a time.

import * as data from '../data.js';
import * as engine from '../engine.js';
import * as settings from '../settings.js';
import { el, add, clear, shuffled, fmtClock, paras } from '../ui.js';
import renderQuizPm from './quizPm.js';
import { figure, figureImg } from '../figures.js';

const KEYS = ['ア', 'イ', 'ウ', 'エ'];
const HOTKEYS = { '1': 0, '2': 1, '3': 2, '4': 3, a: 0, b: 1, c: 2, d: 3 };

export default async function renderQuiz(props) {
  const run = props.ctx.run;
  if (!run) { props.go('home'); return; }
  // 午後 is written, not chosen from four; it has its own screen.
  if (run.written) return renderQuizPm(props);
  return renderQuizAm(props);
}

async function renderQuizAm({ view, extra, go, ctx }) {
  const run = ctx.run;

  const states = new Map(((await data.allStates()) || []).map(s => [s.questionId, s]));
  const body = el('div');
  const nav = el('div', { class: 'navbar' });
  view.append(body, nav);

  let timerId = null;
  let showNav = false;
  let viewing = -1;      // which question the clock below is running against
  // Papers that are graded at the end are answered the way the real exam is:
  // skip what you cannot do, come back to it. That only works if you can see
  // at a glance which numbers are still blank.
  const useNav = run.grading === 'end' && run.items.length > 5;

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
    if (run.grading === 'end') {
      // The answer can still be changed until the paper is handed in, so
      // nothing is written yet: recording here would count every revision as
      // an attempt and move the Leitner box more than once. The result screen
      // settles the whole run in one pass.
      item.selected = key;
      item.elapsedMs = item.shownAt ? Date.now() - item.shownAt : 0;
      draw();
      return;
    }
    if (item.selected !== null) return;
    const prev = states.get(item.id);
    const { state, answer } = engine.grade(run, item, key, prev);
    states.set(item.id, state);
    await data.putState(state);
    await data.addAnswer(answer);
    draw();
  }

  function next() {
    if (run.index < run.items.length - 1) { run.index += 1; draw(); }
    else finish();
  }

  function prev() {
    if (run.index > 0) { run.index -= 1; draw(); }
  }

  function jump(i) {
    if (i >= 0 && i < run.items.length) { run.index = i; showNav = false; draw(); }
  }

  function navPanel() {
    const grid = el('div', { class: 'qnav' });
    run.items.forEach((it, i) => {
      const cls = ['qnav-cell'];
      if (it.selected !== null) cls.push('done');
      if (it.flagged) cls.push('flagged');
      if (i === run.index) cls.push('here');
      grid.append(el('button', {
        class: cls.join(' '),
        onclick: () => jump(i),
        'aria-current': i === run.index ? 'true' : null,
        'aria-label': `問${i + 1} ${it.selected !== null ? '解答済み' : '未解答'}`
                      + (it.flagged ? ' 見直し' : ''),
      }, String(i + 1)));
    });
    const left = run.items.length - engine.answeredCount(run);
    return el('div', { class: 'qnav-panel' },
      grid,
      el('div', { class: 'row', style: 'margin-top:12px' },
        el('span', { class: 'muted', text: left ? `未解答 ${left}問` : '全問解答済み' }),
        el('span', { class: 'spacer' }),
        el('button', {
          class: left ? '' : 'primary',
          onclick: () => {
            if (!left || confirm(`未解答が ${left}問 あります。採点しますか？`)) finish();
          },
        }, '解答を終了する')));
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
    // Restart the per-question clock on arrival, not on every re-render: with
    // free navigation a single shownAt would bill time spent elsewhere to
    // whichever question happened to be open first.
    if (viewing !== run.index) { viewing = run.index; item.shownAt = Date.now(); }
    clear(body);
    clear(nav);

    const sess = data.sessions().find(s => s.id === q.sessionId);
    const graded = item.selected !== null && run.grading === 'immediate';
    const reveal = graded && item.revealed;

    // Past papers repeat: a question that has already been set several times is
    // worth more study than one seen once, so the count leads the tags.
    const group = data.groupOf(q);
    body.append(el('div', { class: 'qmeta' },
      el('span', { class: 'no', text: `${run.index + 1} / ${run.items.length}` }),
      run.mode !== 'exam' && group.length > 1
        ? el('span', { class: 'chip reuse', text: `${group.length}回出題` }) : null,
      run.mode !== 'exam' && sess
        ? el('span', { class: 'chip static', text: `${sess.label} 問${q.no}` }) : null,
      ...(run.mode === 'exam' ? [] : (q.tags || []).map(t =>
        el('span', { class: 'chip static', text: t })))));

    if (run.mode !== 'exam' && group.length > 1) {
      const labels = group.map(g => {
        const s = data.sessions().find(x => x.id === g.sessionId);
        return (s ? s.label : g.sessionId).replace(/年度\s*/, '');
      });
      body.append(el('p', { class: 'muted reuse-list' },
        `初出 ${labels[0]}  /  再出題 ${labels.slice(1).join('、')}`));
    }

    if (useNav) {
      body.append(el('button', {
        class: 'icon ghost flagbtn', 'aria-pressed': String(!!item.flagged),
        onclick: () => { item.flagged = !item.flagged; draw(); },
      }, item.flagged ? '★ 見直す' : '☆ 見直す'));
    }
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
      } else if (q.choicesInFigure) {
        // The four options are one drawing shown above; the buttons just pick.
        // Any text extracted for them is fragmentary — the split failed, which
        // is why the drawing is being used — so it is kept out of the way.
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

    if (useNav && showNav) nav.append(navPanel());
    const left = run.items.length - engine.answeredCount(run);
    add(nav,
      el('button', { onclick: prev, disabled: run.index === 0 }, '前へ'),
      el('span', { class: 'spacer' }),
      useNav
        ? el('button', {
            class: 'icon ghost', 'aria-expanded': String(showNav),
            onclick: () => { showNav = !showNav; draw(); },
          }, left ? `未解答 ${left}` : '一覧')
        : null,
      el('button', {
        class: 'primary',
        onclick: next,
        disabled: run.grading === 'immediate' && item.selected === null,
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
    } else if (k === 'f' && useNav) {
      ev.preventDefault(); item.flagged = !item.flagged; draw();
    } else if (k === 'l' && useNav) {
      ev.preventDefault(); showNav = !showNav; draw();
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
    if (dx < 0) next(); else prev();
  };
  view.addEventListener('touchstart', onStart, { passive: true });
  view.addEventListener('touchend', onEnd, { passive: true });

  await draw();

  return () => {
    if (timerId) clearInterval(timerId);
    document.removeEventListener('keydown', onKey);
  };
}

export { figure, figureImg };

export function explanation(q) {
  return el('div', { class: 'explain' },
    ...paras(q.explanation),
    el('div', { class: 'src', text: '出典: ' + (q.explanationSource || '教科書解説') }));
}

function hash(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}

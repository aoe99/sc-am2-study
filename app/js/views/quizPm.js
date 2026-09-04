// 午後の解答画面。事例を読み、設問に書き、解答例と突き合わせて自分で採点する。
//
// Nothing here can be marked for you. IPA publishes 解答例 — an example of an
// answer — not a key, and grades the real thing by hand. So the screen is built
// around the moment *after* you have written something: your own words, IPA's,
// and the 採点講評 saying what most people got wrong, side by side, and then
// ○ / △ / × in your own judgement. 記号 and 語句 answers that can be compared
// outright are marked for you and shown as a suggestion you can override.

import * as data from '../data.js';
import * as engine from '../engine.js';
import { el, add, clear, fmtClock, paras } from '../ui.js';
import { figure } from '../figures.js';

const MARKS = [
  { value: true, label: '○ 正解', cls: 'ok' },
  { value: engine.PARTIAL, label: '△ 一部', cls: 'partial' },
  { value: false, label: '× 不正解', cls: 'ng' },
];

export default async function renderQuizPm({ view, extra, go, ctx }) {
  const run = ctx.run;
  const states = new Map(((await data.allStates()) || []).map(s => [s.questionId, s]));
  const body = el('div');
  const nav = el('div', { class: 'navbar' });
  view.append(body, nav);

  let timerId = null;
  let showNav = false;
  let showCase = run.mode === 'case' || run.mode === 'exam';
  let viewing = -1;

  if (run.deadline) {
    const clock = el('span', { class: 'timer' });
    extra.append(clock);
    const tick = () => {
      const left = run.deadline - Date.now();     // real time, never a tick count
      clock.textContent = fmtClock(left);
      clock.className = 'timer' + (left <= 0 ? ' danger' : left <= 600000 ? ' warn' : '');
      if (left <= 0) finish();
    };
    tick();
    timerId = setInterval(tick, 500);
    document.addEventListener('visibilitychange', tick);
  } else {
    extra.append(el('button', { class: 'icon ghost', onclick: quit }, '中断'));
  }

  function quit() {
    // 午後 runs are long. Leaving keeps the run, so it can be picked up later.
    if (engine.answeredCount(run) === 0) { ctx.run = null; data.clearRun(); }
    else data.saveRun(run);
    go('home');
  }

  function finish() {
    if (run.finished) return;
    run.finished = true;
    run.endedAt = Date.now();
    if (timerId) clearInterval(timerId);
    ctx.lastResult = run;
    ctx.run = null;
    data.clearRun();
    go('result');
  }

  const jump = i => { run.index = i; showNav = false; draw(); };
  const next = () => (run.index < run.items.length - 1
    ? (run.index += 1, draw()) : finish());
  const prev = () => { if (run.index > 0) { run.index -= 1; draw(); } };

  /** Write the verdict to the study record. Re-marking replaces it. */
  async function mark(item, value) {
    const prev = states.get(item.id);
    const { state, answer } = engine.grade(run, item, value, prev);
    states.set(item.id, state);
    await data.putState(state);
    await data.addAnswer(answer);
    await data.saveRun(run);
    draw();
  }

  /** The 事例, with each 図/表 shown where the booklet prints it.
   *
   *  A drawing that was cropped replaces its own OCR text: those rows are cell
   *  fragments in reading order, which is unreadable next to the picture of the
   *  same table. Where the crop failed the fragments are all there is, so they
   *  are kept — folded away, but kept.
   */
  async function caseNode(c) {
    const box = el('div', { class: 'casebody' });
    if (c.intent) {
      box.append(el('details', { class: 'intent' },
        el('summary', { text: '出題趣旨' }),
        ...paras(c.intent)));
    }
    const byCaption = new Map((c.figures || []).map(f => [f.caption, f]));
    const body = c.body || [];
    // 表 captions print above their table and 図 captions below their figure,
    // so the fragments a crop replaces can lie on either side of it.
    const hidden = new Set();
    body.forEach((b, i) => {
      if (b.kind !== 'caption' || !byCaption.has(b.text)) return;
      for (const step of [1, -1]) {
        for (let j = i + step; j >= 0 && j < body.length; j += step) {
          if (body[j].kind !== 'figure') break;
          hidden.add(j);
        }
      }
    });
    for (let i = 0; i < body.length; i++) {
      const b = body[i];
      if (b.kind === 'heading') {
        box.append(el('h3', { text: b.text }));
      } else if (b.kind === 'caption') {
        const fig = byCaption.get(b.text);
        if (fig) box.append(await figure(fig.file));
        box.append(el('p', { class: 'cap', text: b.text }));
      } else if (b.kind === 'figure') {
        if (!hidden.has(i)) box.append(el('pre', { class: 'figtext', text: b.text }));
      } else {
        box.append(el('p', { text: b.text }));
      }
    }
    return box;
  }

  function navPanel() {
    const grid = el('div', { class: 'qnav' });
    let lastCase = null;
    run.items.forEach((it, i) => {
      const q = data.byId(it.id);
      if (q.caseId !== lastCase) {
        lastCase = q.caseId;
        const c = data.caseById(q.caseId);
        grid.append(el('span', { class: 'qnav-label', text: c ? `問${c.no}` : '' }));
      }
      const cls = ['qnav-cell'];
      if (it.result !== null) cls.push(it.result === true ? 'ok'
        : it.result === engine.PARTIAL ? 'partial' : 'ng');
      else if ((it.typed || []).some(t => t && t.trim())) cls.push('done');
      if (i === run.index) cls.push('here');
      grid.append(el('button', {
        class: cls.join(' '), onclick: () => jump(i),
        'aria-label': `${q.label} ${it.result !== null ? '採点済み' : '未採点'}`,
      }, q.label.replace('設問', '')));
    });
    const left = run.items.length - engine.markedCount(run);
    return el('div', { class: 'qnav-panel' }, grid,
      el('div', { class: 'row', style: 'margin-top:12px' },
        el('span', { class: 'muted', text: left ? `未採点 ${left}問` : '全問採点済み' }),
        el('span', { class: 'spacer' }),
        el('button', {
          class: left ? '' : 'primary',
          onclick: () => {
            if (!left || confirm(`未採点が ${left}問 あります。結果を見ますか？`)) finish();
          },
        }, '結果を見る')));
  }

  async function draw() {
    const item = run.items[run.index];
    const q = data.byId(item.id);
    const c = data.caseOf(q);
    if (viewing !== run.index) { viewing = run.index; item.shownAt = Date.now(); }
    clear(body);
    clear(nav);

    const sess = data.sessions().find(s => s.id === q.sessionId);
    const paper = (data.sectionInfo('pm').papers || [])
      .find(p => p.id === (c && c.paper));
    body.append(el('div', { class: 'qmeta' },
      el('span', { class: 'no', text: `${run.index + 1} / ${run.items.length}` }),
      sess ? el('span', { class: 'chip static' },
        `${sess.label}${paper ? ' ' + paper.label : ''} 問${c ? c.no : ''}`) : null,
      run.mode !== 'exam' && q.commentaryRate
        ? el('span', { class: 'chip rate rate-' + rateClass(q.commentaryRate) },
            `正答率 ${q.commentaryRate}`) : null,
      run.mode !== 'exam'
        ? el('span', { class: 'chip static', text: KIND_LABEL[q.answerKind] || '' }) : null,
      ...(run.mode === 'exam' ? [] : (q.tags || []).map(t =>
        el('span', { class: 'chip static', text: t })))));

    if (c) {
      body.append(el('h2', { class: 'casetitle', text: c.title }));
      const open = el('button', {
        class: 'icon ghost', 'aria-expanded': String(showCase),
        onclick: () => { showCase = !showCase; draw(); },
      }, showCase ? '事例を閉じる' : `事例を読む（${c.pages ? c.pages[1] - c.pages[0] + 1 : '?'}ページ）`);
      body.append(el('p', {}, open));
      if (showCase) {
        body.append(await caseNode(c));
        // Anything the body text never introduced by caption still belongs to
        // the 事例; it goes at the end rather than being dropped.
        const shown = new Set((c.body || []).filter(b => b.kind === 'caption')
          .map(b => b.text));
        for (const f of c.figures || [])
          if (!shown.has(f.caption)) body.append(await figure(f.file));
      }
    }

    body.append(el('div', { class: 'qtext' },
      el('span', { class: 'setsu', text: q.label }),
      q.lead ? el('p', { class: 'lead', text: q.lead }) : null,
      ...paras(q.text || '（設問文を取り出せませんでした。解答例と解説で学習してください）')));

    // One box per 空欄, because that is how the answer sheet is laid out and
    // how a half-right answer earns its △.
    const parts = q.parts && q.parts.length ? q.parts : [{ label: null, answer: '' }];
    const form = el('div', { class: 'answers' });
    parts.forEach((p, i) => {
      const ta = el('textarea', {
        rows: p.kind === 'essay' ? 3 : 1,
        placeholder: p.kind === 'choice' ? '記号' : p.kind === 'term' ? '語句' : '解答',
        oninput: ev => { item.typed[i] = ev.target.value; data.saveRun(run); },
      });
      ta.value = (item.typed || [])[i] || '';
      form.append(el('label', { class: 'answer' },
        el('span', { class: 'blank', text: p.label ? `${p.label}` : `解答${parts.length > 1 ? i + 1 : ''}` }),
        ta));
    });
    body.append(form);

    if (!item.revealed) {
      body.append(el('p', {}, el('button', {
        class: 'primary wide',
        onclick: () => { item.revealed = true; draw(); },
      }, '解答例と照らす')));
    } else {
      body.append(await verdictNode(q, item));
    }

    if (showNav) nav.append(navPanel());
    const left = run.items.length - engine.markedCount(run);
    add(nav,
      el('button', { onclick: prev, disabled: run.index === 0 }, '前へ'),
      el('span', { class: 'spacer' }),
      el('button', {
        class: 'icon ghost', 'aria-expanded': String(showNav),
        onclick: () => { showNav = !showNav; draw(); },
      }, left ? `未採点 ${left}` : '一覧'),
      el('button', { class: 'primary', onclick: next },
        run.index === run.items.length - 1 ? '結果を見る' : '次へ'));
  }

  async function verdictNode(q, item) {
    const box = el('div', { class: 'reveal' });
    const auto = engine.autoResult(q, item.typed);
    const parts = q.parts && q.parts.length ? q.parts : [];

    box.append(el('h3', { text: '解答例（IPA）' }));
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
    box.append(table);
    if (q.remarks && q.remarks.length)
      box.append(el('p', { class: 'muted', text: '備考: ' + q.remarks.join(' / ') }));

    // IPA's own post-mortem. 午前 has no equivalent, and for a 記述 answer it is
    // the difference between marking honestly and marking generously. IPA only
    // writes about the 設問 that went badly, so where there is none the 大問's
    // own paragraph stands in — it is still their reading of the whole case.
    const c2 = data.caseOf(q);
    const text = q.commentary || (c2 && c2.overview) || '';
    const rate = q.commentary ? q.commentaryRate : (c2 && c2.overviewRate);
    if (text) {
      box.append(el('h3', {},
        q.commentary ? '採点講評' : '採点講評（この大問の全体）',
        rate ? el('span', { class: 'chip rate rate-' + rateClass(rate) },
                  `正答率 ${rate}`) : null));
      box.append(el('div', { class: 'commentary' }, ...paras(text)));
    }

    if (q.explanation) {
      box.append(el('details', { class: 'explain-fold' },
        el('summary', { text: `解説（設問${q.setsu}）` }),
        el('div', { class: 'explain' }, ...paras(q.explanation),
          el('div', { class: 'src', text: '出典: ' + (q.explanationSource || '教科書解説') }))));
    }

    box.append(el('h3', { text: '自己採点' }));
    if (auto !== null) {
      box.append(el('p', { class: 'muted' },
        auto === true ? '解答例と一致しています。'
          : auto === engine.PARTIAL ? '一部が解答例と一致しています。'
          : '解答例と一致しませんでした。'));
    }
    const suggest = item.result !== null ? item.result : auto;
    const row = el('div', { class: 'marks' });
    for (const m of MARKS) {
      row.append(el('button', {
        class: 'mark ' + m.cls,
        'aria-pressed': String(item.result === m.value
          || (item.result === null && suggest === m.value)),
        onclick: () => mark(item, m.value),
      }, m.label));
    }
    box.append(row);
    if (item.result === null)
      box.append(el('p', { class: 'muted', text: '採点すると学習記録に残ります。' }));
    return box;
  }

  function onKey(ev) {
    if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
    if (/^(INPUT|TEXTAREA)$/.test((ev.target.tagName || '').toUpperCase())) return;
    const item = run.items[run.index];
    const k = ev.key.toLowerCase();
    if (k === 'enter') { ev.preventDefault(); next(); }
    else if (k === 'c') { ev.preventDefault(); showCase = !showCase; draw(); }
    else if (k === 'l') { ev.preventDefault(); showNav = !showNav; draw(); }
    else if (k === 's') { ev.preventDefault(); item.revealed = !item.revealed; draw(); }
    else if (item.revealed && ['1', '2', '3'].includes(k)) {
      ev.preventDefault(); mark(item, MARKS[Number(k) - 1].value);
    }
  }
  document.addEventListener('keydown', onKey);

  await draw();
  return () => {
    if (timerId) clearInterval(timerId);
    document.removeEventListener('keydown', onKey);
  };
}

const KIND_LABEL = { choice: '記号選択', term: '語句', essay: '記述' };
const rateClass = r => ({ '高': 'hi', 'やや高': 'hi', '平均': 'mid',
                          'やや低': 'lo', '低': 'lo' })[r] || 'mid';

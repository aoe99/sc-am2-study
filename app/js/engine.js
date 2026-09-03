// Builds a run of questions for a mode and keeps score while it is answered.

import * as data from './data.js';
import * as leitner from './leitner.js';
import { shuffled } from './ui.js';

export const MODES = {
  practice: { label: '練習', timed: false, reveal: true },
  exam:     { label: '本番', timed: true,  reveal: false, count: 25, minutes: 40 },
  review:   { label: '復習', timed: false, reveal: true },
  session:  { label: '年度別', timed: false, reveal: true, count: 25 },
};

export const PASS_RATIO = 0.6;   // 25問中15問

/** Collapse re-used questions to one entry, preferring the earliest sitting. */
function dedupe(list) {
  const seen = new Set();
  const out = [];
  for (const q of list) {
    if (q.duplicateGroupId) {
      if (seen.has(q.duplicateGroupId)) continue;
      seen.add(q.duplicateGroupId);
      const group = data.groupOf(q);
      out.push(group[0] || q);
    } else {
      out.push(q);
    }
  }
  return out;
}

/**
 * @param {object} opts
 *   mode, count, sessionIds[], tags[], onlyUnseen, onlyWrong, merge, grading
 */
export function build(opts, states) {
  const stateBy = new Map((states || []).map(s => [s.questionId, s]));
  let pool = data.questions();

  if (opts.mode === 'session') {
    pool = pool.filter(q => q.sessionId === opts.sessionId);
    return { list: pool.slice().sort((a, b) => a.no - b.no), stateBy };
  }

  if (opts.sessionIds && opts.sessionIds.length)
    pool = pool.filter(q => opts.sessionIds.includes(q.sessionId));
  if (opts.tags && opts.tags.length)
    pool = pool.filter(q => (q.tags || []).some(t => opts.tags.includes(t)));

  if (opts.mode === 'review') {
    const now = Date.now();
    pool = pool.filter(q => leitner.isDue(stateBy.get(q.id), now));
  } else {
    if (opts.onlyUnseen) pool = pool.filter(q => !(stateBy.get(q.id) || {}).attempts);
    if (opts.onlyWrong) pool = pool.filter(q => (stateBy.get(q.id) || {}).lastResult === false);
  }

  // §5-6: 本番モードと年度別は常に回ごとの扱い。
  if (opts.merge && opts.mode !== 'exam') pool = dedupe(pool);

  const seed = (Date.now() ^ (pool.length * 2654435761)) >>> 0;
  let list = shuffled(pool, seed);
  const want = opts.mode === 'exam' ? MODES.exam.count : opts.count;
  if (want && want > 0 && want < list.length) list = list.slice(0, want);
  return { list, stateBy };
}

export function createRun(list, opts) {
  return {
    mode: opts.mode,
    grading: opts.mode === 'exam' ? 'end' : (opts.grading || 'immediate'),
    shuffleChoices: !!opts.shuffleChoices,
    startedAt: Date.now(),
    deadline: opts.mode === 'exam'
      ? Date.now() + MODES.exam.minutes * 60000 : null,
    index: 0,
    items: list.map(q => ({
      id: q.id, selected: null, correct: null,
      shownAt: 0, elapsedMs: 0, revealed: false,
    })),
    sessionLabel: opts.sessionLabel || null,
  };
}

export const scoreOf = run => run.items.filter(i => i.correct === true).length;
export const answeredCount = run => run.items.filter(i => i.selected !== null).length;
export const passed = run => scoreOf(run) / run.items.length >= PASS_RATIO;

/** Record one answer against the run and return the updated Leitner state. */
export function grade(run, item, key, prevState) {
  const q = data.byId(item.id);
  item.selected = key;
  item.correct = key === q.answer;
  item.elapsedMs = item.shownAt ? Date.now() - item.shownAt : 0;
  const next = leitner.advance(prevState || leitner.blank(item.id), item.correct);
  return {
    state: next,
    answer: {
      questionId: item.id,
      answeredAt: Date.now(),
      selected: key,
      correct: item.correct,
      mode: run.mode,
      elapsedMs: item.elapsedMs,
    },
  };
}

// Builds a run of questions for a mode and keeps score while it is answered.

import * as data from './data.js';
import * as leitner from './leitner.js';
import { shuffled } from './ui.js';

export const MODES = {
  practice: { label: '練習', timed: false, reveal: true },
  exam:     { label: '本番', timed: true,  reveal: false },
  review:   { label: '復習', timed: false, reveal: true },
  session:  { label: '年度別', timed: false, reveal: true },
  case:     { label: '事例別', timed: false, reveal: true },
};

/** 午前I is 30問50分, 午前II is 25問40分 — both read from the imported pack. */
export function examConfig(section, paper) {
  const info = data.sectionInfo(section);
  if (info.style === 'written') {
    const papers = info.papers || [];
    const p = papers.find(x => x.id === paper) || papers[0] || {};
    return { count: 0, minutes: p.minutes || 150, cases: p.cases || 4,
             choose: p.choose || 2, paper: p.id };
  }
  return { count: info.count || 25, minutes: info.minutes || 40 };
}

export const PASS_RATIO = 0.6;   // 25問中15問

// --- 採点 -----------------------------------------------------------------

export const PARTIAL = leitner.PARTIAL;

/** Fold away everything that is not the answer: spacing, punctuation, width. */
export function normalize(s) {
  return String(s == null ? '' : s)
    .normalize('NFKC')
    .replace(/[\s\u3000]+/g, '')
    .replace(/[，、,]/g, ',')
    .replace(/[。．.]+$/g, '')
    .replace(/["'“”‘’`´]/g, '')
    .toLowerCase();
}

/** Did this typed answer match the printed one closely enough to say so?
 *
 *  Only 記号 and short 語句 are decided here. A 記述 answer is graded by the
 *  person who wrote it against the 解答例 and the 採点講評 — no string comparison
 *  can tell "組織的な対策が抜けている" from a wording difference.
 */
export function autoMark(part, typed) {
  if (!part || part.kind === 'essay') return null;
  const got = normalize(typed);
  if (!got) return false;
  const want = [part.answer, ...(part.options || [])].map(normalize).filter(Boolean);
  return want.includes(got);
}

/** The verdict a whole 設問 gets from its parts, or null if any needs a human. */
export function autoResult(q, typed) {
  if (!q || !q.parts || !q.parts.length) return null;
  const marks = q.parts.map((p, i) => autoMark(p, (typed || [])[i]));
  if (marks.some(m => m === null)) return null;
  if (marks.every(Boolean)) return true;
  return marks.some(Boolean) ? PARTIAL : false;
}

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
  let pool = data.questions().filter(q => data.sectionOf(q) === opts.section);

  // 午後 is answered a 大問 at a time: the ten pages of 事例 are the point, and
  // the 設問 only make sense read against them in order.
  if (opts.mode === 'case') {
    const ids = opts.caseIds && opts.caseIds.length ? opts.caseIds : [opts.caseId];
    const order = new Map(ids.map((id, i) => [id, i]));
    pool = pool.filter(q => order.has(q.caseId));
    return {
      list: pool.slice().sort((a, b) =>
        order.get(a.caseId) - order.get(b.caseId) || a.no - b.no),
      stateBy,
    };
  }

  if (opts.mode === 'session') {
    pool = pool.filter(q => q.sessionId === opts.sessionId);
    return { list: pool.slice().sort((a, b) => a.no - b.no), stateBy };
  }

  if (opts.sessionIds && opts.sessionIds.length)
    pool = pool.filter(q => opts.sessionIds.includes(q.sessionId));
  if (opts.tags && opts.tags.length)
    pool = pool.filter(q => (q.tags || []).some(t => opts.tags.includes(t)));

  if (opts.caseIds && opts.caseIds.length)
    pool = pool.filter(q => opts.caseIds.includes(q.caseId));
  if (opts.kinds && opts.kinds.length)
    pool = pool.filter(q => opts.kinds.includes(q.answerKind));

  if (opts.mode === 'review') {
    const now = Date.now();
    pool = pool.filter(q => leitner.isDue(stateBy.get(q.id), now));
  } else {
    if (opts.onlyUnseen) pool = pool.filter(q => !(stateBy.get(q.id) || {}).attempts);
    if (opts.onlyWrong) pool = pool.filter(q => (stateBy.get(q.id) || {}).lastResult === false);
    // Questions IPA has already set more than once are the ones most likely
    // to come round again.
    if (opts.onlyReused) pool = pool.filter(q => data.groupOf(q).length > 1);
  }

  // §5-6: 本番モードと年度別は常に回ごとの扱い。
  if (opts.merge && opts.mode !== 'exam') pool = dedupe(pool);

  const seed = (Date.now() ^ (pool.length * 2654435761)) >>> 0;
  const want = opts.mode === 'exam' ? examConfig(opts.section).count : opts.count;

  // 午後 is drawn a 事例 at a time even when the filter picked out scattered
  // 設問. The Leitner box is per 設問 — that part was right — but the *reading*
  // is per 事例: shuffling 設問 across 90 case studies means opening a fresh ten
  // pages for every question, and the wording of one 設問 refers to the last.
  // So the shuffle happens over 事例, and every 設問 of a 事例 that made the cut
  // stays together and in the booklet's order.
  // 午後 is counted in 事例, not 設問: a case study is 20 to 45 minutes of work
  // and the number you want to sit down and do is a number of *those*.
  if (data.isWritten(opts.section))
    return { list: byCase(pool, seed, opts.caseCount), stateBy };

  let list = shuffled(pool, seed);
  if (want && want > 0 && want < list.length) list = list.slice(0, want);
  return { list, stateBy };
}

/** Group the pool into 事例, shuffle those, and take `wantCases` of them whole. */
export function byCase(pool, seed, wantCases) {
  const buckets = new Map();
  for (const q of pool) {
    if (!buckets.has(q.caseId)) buckets.set(q.caseId, []);
    buckets.get(q.caseId).push(q);
  }
  for (const items of buckets.values()) items.sort((a, b) => a.no - b.no);
  let order = shuffled([...buckets.keys()], seed);
  if (wantCases > 0) order = order.slice(0, wantCases);
  return order.flatMap(id => buckets.get(id));
}

/** How many 事例 a filtered pool covers. */
export const caseCountOf = list => new Set(list.map(q => q.caseId)).size;

export function createRun(list, opts) {
  const written = data.isWritten(opts.section);
  const timed = opts.mode === 'exam' || (written && opts.minutes > 0);
  const minutes = opts.minutes || examConfig(opts.section, opts.paper).minutes;
  return {
    mode: opts.mode,
    written,
    // 午後 is never marked as you go: there is no key to check against until
    // you have written the answer and read the 解答例 next to it.
    grading: (opts.mode === 'exam' || written) ? 'end' : (opts.grading || 'immediate'),
    shuffleChoices: !written && !!opts.shuffleChoices,
    startedAt: Date.now(),
    section: opts.section,
    paper: opts.paper || null,
    caseIds: opts.caseIds || null,
    deadline: timed ? Date.now() + minutes * 60000 : null,
    index: 0,
    items: list.map(q => ({
      id: q.id, selected: null, correct: null, result: null,
      typed: written ? (q.parts || [{}]).map(() => '') : null,
      shownAt: 0, elapsedMs: 0, revealed: false,
    })),
    sessionLabel: opts.sessionLabel || null,
  };
}

export const scoreOf = run => run.items.filter(i => i.result === true).length;
export const partialCount = run => run.items.filter(i => i.result === PARTIAL).length;
/** A 記述 answer counts as answered once it has been written, marked or not. */
export const answeredCount = run => run.items.filter(
  i => (run.written ? (i.typed || []).some(t => t && t.trim()) : i.selected !== null)
       || i.result !== null).length;
export const markedCount = run => run.items.filter(i => i.result !== null).length;
/** 午後 is 60% too, and a half-mark is worth half a question. */
export const scoreRatio = run =>
  run.items.length
    ? (scoreOf(run) + partialCount(run) * 0.5) / run.items.length : 0;
export const passed = run => scoreRatio(run) >= PASS_RATIO;

/**
 * Record one answer against the run and return the updated Leitner state.
 * `value` is the chosen key for 午前, or true / PARTIAL / false for 午後.
 */
export function grade(run, item, value, prevState) {
  const q = data.byId(item.id);
  if (run.written) {
    item.result = value;
    item.correct = value === true;
  } else {
    item.selected = value;
    item.correct = value === q.answer;
    item.result = item.correct;
  }
  // A paper graded at the end already timed each answer as it was given;
  // measuring again here would bill the whole rest of the sitting to it.
  if (!item.elapsedMs) item.elapsedMs = item.shownAt ? Date.now() - item.shownAt : 0;
  const next = leitner.advance(prevState || leitner.blank(item.id), item.result);
  return {
    state: next,
    answer: {
      questionId: item.id,
      answeredAt: Date.now(),
      selected: run.written ? null : value,
      // What was actually written is kept: re-reading your own wrong wording
      // beside the 解答例 is most of what makes a 記述 answer stick.
      typed: run.written ? (item.typed || []).slice() : null,
      correct: item.correct,
      result: item.result,
      mode: run.mode,
      elapsedMs: item.elapsedMs,
    },
  };
}

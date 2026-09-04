// Leitner scheduling (§5-3). Five boxes; a correct answer promotes, a wrong
// one drops straight back to box 1.
//
// 午後 is marked by hand against IPA's 解答例, and "half right" is the honest
// verdict for most 記述 answers — the 採点講評 exists precisely because these are
// not pass/fail. Forcing that into ○ or × would make the boxes lie: rounding up
// retires a question you cannot actually answer, rounding down buries one you
// nearly can. So a result is true / 'partial' / false, and a partial holds the
// question where it is — reviewed again on the same schedule, not promoted.

export const INTERVALS_DAYS = { 1: 0, 2: 1, 3: 3, 4: 7, 5: 16 };
export const MASTERED_DAYS = 35;   // box 5 answered correctly again
const DAY = 86400000;

/** Start of tomorrow, so "1日後" means the next calendar day, not +24h. */
function dayAfter(from, days) {
  if (days === 0) return from;                 // same day: due immediately
  const d = new Date(from);
  d.setHours(0, 0, 0, 0);
  return d.getTime() + days * DAY;
}

export const PARTIAL = 'partial';

export function blank(questionId) {
  return {
    questionId, attempts: 0, corrects: 0, partials: 0, lastResult: null,
    leitnerBox: 1, dueAt: 0, lastAnsweredAt: 0,
  };
}

export function advance(state, result, now = Date.now()) {
  const s = { ...blank(state && state.questionId), ...(state || {}) };
  s.attempts += 1;
  if (result === true) s.corrects += 1;
  else if (result === PARTIAL) s.partials = (s.partials || 0) + 1;
  s.lastResult = result;
  s.lastAnsweredAt = now;
  const box = s.leitnerBox || 1;
  if (result === PARTIAL) {
    s.leitnerBox = box;                        // held, not promoted
    s.dueAt = dayAfter(now, INTERVALS_DAYS[box] ?? 0);
  } else if (!result) {
    s.leitnerBox = 1;
    s.dueAt = now;                             // wrong answers come back today
  } else if (box >= 5) {
    s.leitnerBox = 5;
    s.dueAt = dayAfter(now, MASTERED_DAYS);
  } else {
    s.leitnerBox = box + 1;
    s.dueAt = dayAfter(now, INTERVALS_DAYS[box + 1]);
  }
  return s;
}

export const isDue = (state, now = Date.now()) =>
  !!state && state.attempts > 0 && (state.dueAt || 0) <= now;

export function boxCounts(states) {
  const out = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 };
  for (const s of states) if (s.attempts > 0) out[s.leitnerBox || 1] += 1;
  return out;
}

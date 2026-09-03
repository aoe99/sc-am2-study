// Import, hold and export the question corpus and the study record.

import * as db from './db.js';

const state = {
  loaded: false,
  meta: null,
  sessions: [],
  questions: [],
  byId: new Map(),
  groups: new Map(),   // duplicateGroupId → [question…] in sitting order
};

const urlCache = new Map();

export const meta = () => state.meta;
export const sessions = () => state.sessions;
export const questions = () => state.questions;
export const byId = id => state.byId.get(id);
export const isLoaded = () => state.loaded;
export const groupOf = q =>
  (q.duplicateGroupId ? state.groups.get(q.duplicateGroupId) : null) || [q];

/** Read the file the user picked and write it into IndexedDB. */
export async function importPack(file, onProgress = () => {}) {
  onProgress('ファイルを読み込み中…');
  const text = await file.text();
  let doc;
  try {
    doc = JSON.parse(text);
  } catch {
    throw new Error('JSON として読めませんでした。ファイルを確認してください。');
  }
  if (!doc || !Array.isArray(doc.questions) || !Array.isArray(doc.sessions))
    throw new Error('questions / sessions が見つかりません。sc-data.json を選んでください。');
  if (!doc.questions.length)
    throw new Error('問題が 0 件です。');

  onProgress('既存のデータを置き換え中…');
  // Object URLs point at the blobs we are about to drop; releasing them here
  // is what stops a re-import from still showing the previous figures.
  for (const url of urlCache.values()) URL.revokeObjectURL(url);
  urlCache.clear();
  await db.clear(db.STORES.questions);
  await db.clear(db.STORES.sessions);
  await db.clear(db.STORES.assets);

  onProgress(`問題 ${doc.questions.length} 件を保存中…`);
  await db.putMany(db.STORES.questions, doc.questions);
  await db.putMany(db.STORES.sessions, doc.sessions);

  const assets = doc.assets || {};
  const paths = Object.keys(assets);
  if (paths.length) {
    // Store the artwork as Blobs, not as the data: URI strings it arrived as —
    // holding 8MB of base64 in memory on a phone is what makes the app crawl.
    const rows = [];
    for (let i = 0; i < paths.length; i++) {
      if (i % 40 === 0) onProgress(`図表 ${i}/${paths.length} を変換中…`);
      const blob = await (await fetch(assets[paths[i]])).blob();
      rows.push({ path: paths[i], blob });
    }
    await db.putMany(db.STORES.assets, rows);
  }

  const info = {
    ...(doc.meta || {}),
    importedAt: Date.now(),
    fileName: file.name,
    assetCount: paths.length,
  };
  await db.put(db.STORES.kv, info, 'meta');
  onProgress('完了');
  await load(true);
  return info;
}

export async function load(force = false) {
  if (state.loaded && !force) return state;
  const [metaRow, qs, ss] = await Promise.all([
    db.get(db.STORES.kv, 'meta'),
    db.getAll(db.STORES.questions),
    db.getAll(db.STORES.sessions),
  ]);
  state.meta = metaRow || null;
  state.sessions = (ss || []).sort((a, b) =>
    a.year - b.year || (a.term === 'haru' ? 0 : 1) - (b.term === 'haru' ? 0 : 1));
  const order = new Map(state.sessions.map((s, i) => [s.id, i]));
  state.questions = (qs || []).sort((a, b) =>
    (order.get(a.sessionId) ?? 0) - (order.get(b.sessionId) ?? 0) || a.no - b.no);
  state.byId = new Map(state.questions.map(q => [q.id, q]));
  state.groups = new Map();
  for (const q of state.questions) {
    if (!q.duplicateGroupId) continue;
    if (!state.groups.has(q.duplicateGroupId)) state.groups.set(q.duplicateGroupId, []);
    state.groups.get(q.duplicateGroupId).push(q);
  }
  state.loaded = state.questions.length > 0;
  return state;
}

/** Object URL for a figure, created once and kept for the page's lifetime. */
export async function figureUrl(path) {
  if (urlCache.has(path)) return urlCache.get(path);
  const row = await db.get(db.STORES.assets, path);
  if (!row || !row.blob) return null;
  const url = URL.createObjectURL(row.blob);
  urlCache.set(path, url);
  return url;
}

export const allTags = () => {
  const t = new Set();
  for (const q of state.questions) for (const x of q.tags || []) t.add(x);
  return [...t].sort();
};

// --- study record ---------------------------------------------------------

export const allStates = () => db.getAll(db.STORES.states);
export const stateOf = id => db.get(db.STORES.states, id);
export const putState = s => db.put(db.STORES.states, s);
export const allAnswers = () => db.getAll(db.STORES.answers);
export const addAnswer = a => db.put(db.STORES.answers, a);

/** Everything the user would lose if Safari cleared site data. */
export async function exportProgress(settings) {
  const [answers, states] = await Promise.all([allAnswers(), allStates()]);
  return {
    kind: 'sc-am2-progress',
    version: 1,
    exportedAt: new Date().toISOString(),
    dataMeta: state.meta ? { generatedAt: state.meta.generatedAt } : null,
    settings,
    answers: (answers || []).map(({ seq, ...rest }) => rest),
    states: states || [],
  };
}

export async function importProgress(obj, { merge = false } = {}) {
  if (!obj || obj.kind !== 'sc-am2-progress')
    throw new Error('学習記録のファイルではないようです。');
  if (!merge) {
    await db.clear(db.STORES.answers);
    await db.clear(db.STORES.states);
  }
  await db.putMany(db.STORES.answers, obj.answers || []);
  if (merge) {
    // Keep whichever record is further along for each question.
    const existing = new Map(((await allStates()) || []).map(s => [s.questionId, s]));
    const merged = (obj.states || []).map(s => {
      const cur = existing.get(s.questionId);
      if (!cur) return s;
      return (s.lastAnsweredAt || 0) > (cur.lastAnsweredAt || 0) ? s : cur;
    });
    await db.putMany(db.STORES.states, merged);
  } else {
    await db.putMany(db.STORES.states, obj.states || []);
  }
  return { answers: (obj.answers || []).length, states: (obj.states || []).length };
}

export const wipeAll = () => db.clearAll();
export const wipeProgress = () => db.clearProgress();

// Import, hold and export the question corpus and the study record.

import * as db from './db.js';

const state = {
  loaded: false,
  meta: null,
  sessions: [],
  questions: [],
  cases: [],
  byId: new Map(),
  caseById: new Map(),
  itemsByCase: new Map(),   // caseId → [question…] in booklet order
  groups: new Map(),        // duplicateGroupId → [question…] in sitting order
};

const urlCache = new Map();

export const meta = () => state.meta;
export const sessions = () => state.sessions;
export const cases = () => state.cases;
export const questions = () => state.questions;

const SECTION_ORDER = ['am1', 'am2', 'pm'];

/** Section descriptors, gathered across every pack that has been imported.
 *
 *  Each pack only describes its own 区分, so the switch on the home screen is
 *  the union of them — importing 午後 must not make 午前 disappear.
 */
export function sections() {
  const seen = new Map();
  const packs = (state.meta && state.meta.packs) || null;
  const lists = packs ? Object.values(packs).map(p => p.sections)
                      : [(state.meta || {}).sections];
  for (const list of lists)
    for (const s of list || []) if (s && s.id && !seen.has(s.id)) seen.set(s.id, s);
  if (!seen.size)
    return [{ id: 'am2', label: '午前Ⅱ', count: 25, minutes: 40, style: 'choice',
              questionCount: state.questions.length }];
  return [...seen.values()].sort(
    (a, b) => SECTION_ORDER.indexOf(a.id) - SECTION_ORDER.indexOf(b.id));
}

export const sectionOf = q => q.section || 'am2';
export const sectionInfo = id => sections().find(s => s.id === id) || sections()[0];
export const inSection = id => state.questions.filter(q => sectionOf(q) === id);
export const byId = id => state.byId.get(id);
export const isLoaded = () => state.loaded;

/** 午後 is answered in prose and marked by hand; 午前 is four choices. */
export const styleOf = id => (sectionInfo(id) || {}).style || 'choice';
export const isWritten = id => styleOf(id) === 'written';
export const caseById = id => state.caseById.get(id);
export const caseOf = q => (q && q.caseId) ? state.caseById.get(q.caseId) : null;
export const itemsOfCase = id => state.itemsByCase.get(id) || [];
export const casesIn = id => state.cases.filter(c => c.section === id);

/** When the pack for this 区分 was generated — each ships on its own now. */
export function metaFor(section) {
  const m = state.meta || {};
  const packs = m.packs || {};
  for (const p of Object.values(packs))
    if ((p.sectionIds || []).includes(section)) return p;
  return m;
}
export const groupOf = q =>
  (q.duplicateGroupId ? state.groups.get(q.duplicateGroupId) : null) || [q];

/** Which 区分 a pack carries. Older packs predate the field; read the rows. */
function sectionsOfPack(doc) {
  const declared = ((doc.meta || {}).sections || []).map(s => s.id).filter(Boolean);
  if (declared.length) return declared;
  return [...new Set((doc.questions || []).map(q => q.section || 'am2'))];
}

const figuresOf = row => [
  ...(row.figures || []).map(f => (typeof f === 'string' ? f : f && f.file)),
  ...Object.values(row.choiceFigures || {}),
].filter(Boolean);

const FIG_MAGIC = 'SCFIG1\n';

/** Is this the figures sidecar rather than a question pack? */
async function isFigureFile(file) {
  const head = new Uint8Array(await file.slice(0, FIG_MAGIC.length).arrayBuffer());
  return String.fromCharCode(...head) === FIG_MAGIC;
}

/** Load the figures sidecar: one ArrayBuffer, sliced into Blobs.
 *
 *  午後 ships 668 diagrams, 60MB of JPEG. Carried as data: URIs inside the JSON
 *  they would make it an 84MB string that then parses into another 84MB of the
 *  same bytes, which is what a phone runs out of memory on. Here nothing is
 *  decoded and nothing is copied into a string: the header says where each
 *  picture starts and Blob takes it straight from the buffer.
 */
export async function importFigures(file, onProgress = () => {}) {
  onProgress('図表ファイルを読み込み中…');
  const buf = await file.arrayBuffer();
  const view = new DataView(buf);
  const headLen = view.getUint32(FIG_MAGIC.length, true);
  const start = FIG_MAGIC.length + 4;
  let head;
  try {
    head = JSON.parse(new TextDecoder().decode(
      new Uint8Array(buf, start, headLen)));
  } catch {
    throw new Error('図表ファイルの見出しを読めませんでした。');
  }
  const entries = head.entries || [];
  if (!entries.length) throw new Error('図表が 0 件です。');

  const base = start + headLen;
  // Written in batches so a 668-picture import is not 668 transactions, and so
  // the progress line actually moves on a phone.
  const CHUNK = 40;
  for (let i = 0; i < entries.length; i += CHUNK) {
    onProgress(`図表 ${i}/${entries.length} を保存中…`);
    const rows = entries.slice(i, i + CHUNK).map(e => ({
      path: e.p,
      blob: new Blob([buf.slice(base + e.o, base + e.o + e.l)],
                     { type: e.t || 'image/jpeg' }),
    }));
    for (const r of rows) {
      const url = urlCache.get(r.path);
      if (url) { URL.revokeObjectURL(url); urlCache.delete(r.path); }
    }
    await db.putMany(db.STORES.assets, rows);
  }
  onProgress('完了');
  return { figureCount: entries.length, group: head.group || null,
           fileName: file.name };
}

/** Read the file the user picked and write it into IndexedDB.
 *
 *  A pack replaces only the 区分 it declares. 午前 and 午後 ship as separate
 *  files — together they would be too big for Safari to read in one go — so
 *  importing one must leave the other, and every answer already given against
 *  it, exactly where it was.
 */
export async function importPack(file, onProgress = () => {}) {
  if (await isFigureFile(file)) return importFigures(file, onProgress);
  onProgress('ファイルを読み込み中…');
  const text = await file.text();
  let doc;
  try {
    doc = JSON.parse(text);
  } catch {
    throw new Error('JSON として読めませんでした。ファイルを確認してください。');
  }
  if (!doc || !Array.isArray(doc.questions) || !Array.isArray(doc.sessions))
    throw new Error('questions / sessions が見つかりません。sc-data-am.json などを選んでください。');
  if (!doc.questions.length)
    throw new Error('問題が 0 件です。');

  const secs = sectionsOfPack(doc);
  const mine = id => secs.includes(id || 'am2');
  const newCases = Array.isArray(doc.cases) ? doc.cases : [];

  onProgress('入れ替える範囲を確認中…');
  const [oldQs, oldCases] = await Promise.all([
    db.getAll(db.STORES.questions), db.getAll(db.STORES.cases),
  ]);
  const dropQ = (oldQs || []).filter(q => mine(q.section));
  const dropC = (oldCases || []).filter(c => mine(c.section));
  // Artwork is shared by path, so only drop what nothing left behind still uses.
  const keep = new Set();
  for (const r of (oldQs || []).filter(q => !mine(q.section))) figuresOf(r).forEach(f => keep.add(f));
  for (const r of (oldCases || []).filter(c => !mine(c.section))) figuresOf(r).forEach(f => keep.add(f));
  const dropAssets = new Set();
  for (const r of [...dropQ, ...dropC])
    for (const f of figuresOf(r)) if (!keep.has(f)) dropAssets.add(f);

  // Object URLs point at blobs about to be dropped; releasing them here is what
  // stops a re-import from still showing the previous figures.
  for (const [path, url] of urlCache) {
    if (dropAssets.has(path)) { URL.revokeObjectURL(url); urlCache.delete(path); }
  }

  onProgress(`既存の ${dropQ.length} 問を置き換え中…`);
  await db.delMany(db.STORES.questions, dropQ.map(q => q.id));
  await db.delMany(db.STORES.cases, dropC.map(c => c.id));
  await db.delMany(db.STORES.assets, [...dropAssets]);

  onProgress(`問題 ${doc.questions.length} 件を保存中…`);
  await db.putMany(db.STORES.questions, doc.questions);
  if (newCases.length) await db.putMany(db.STORES.cases, newCases);
  // Sessions are shared between 区分; upsert them rather than replacing.
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

  const group = (doc.meta || {}).packGroup || secs.join(',');
  const prev = (await db.get(db.STORES.kv, 'meta')) || {};
  const entry = {
    ...(doc.meta || {}),
    // The descriptors drive the 区分 switch; the plain ids say which rows this
    // pack owns. Keeping both apart is what stopped the switch reading a list
    // of strings and falling back to a single 午前Ⅱ tab.
    sections: (doc.meta || {}).sections
      || secs.map(id => ({ id, label: id, style: 'choice' })),
    sectionIds: secs,
    importedAt: Date.now(),
    fileName: file.name,
    assetCount: paths.length,
  };
  const packs = { ...(prev.packs || {}) };
  // A 区分 may only belong to one pack: importing a combined file has to retire
  // the split ones it supersedes, or the home screen would show two dates.
  for (const [k, v] of Object.entries(packs))
    if ((v.sectionIds || []).some(mine)) delete packs[k];
  packs[group] = entry;
  const info = { ...entry, packs };
  await db.put(db.STORES.kv, info, 'meta');
  onProgress('完了');
  await load(true);
  return info;
}

export async function load(force = false) {
  if (state.loaded && !force) return state;
  const [metaRow, qs, ss, cs] = await Promise.all([
    db.get(db.STORES.kv, 'meta'),
    db.getAll(db.STORES.questions),
    db.getAll(db.STORES.sessions),
    db.getAll(db.STORES.cases),
  ]);
  state.meta = metaRow || null;
  state.sessions = (ss || []).sort((a, b) =>
    a.year - b.year || (a.term === 'haru' ? 0 : 1) - (b.term === 'haru' ? 0 : 1));
  const order = new Map(state.sessions.map((s, i) => [s.id, i]));
  state.questions = (qs || []).sort((a, b) =>
    (order.get(a.sessionId) ?? 0) - (order.get(b.sessionId) ?? 0) || a.no - b.no);
  state.byId = new Map(state.questions.map(q => [q.id, q]));
  state.cases = (cs || []).sort((a, b) =>
    (order.get(a.sessionId) ?? 0) - (order.get(b.sessionId) ?? 0)
    || String(a.paper).localeCompare(String(b.paper)) || a.no - b.no);
  state.caseById = new Map(state.cases.map(c => [c.id, c]));
  state.itemsByCase = new Map();
  for (const q of state.questions) {
    if (!q.caseId) continue;
    if (!state.itemsByCase.has(q.caseId)) state.itemsByCase.set(q.caseId, []);
    state.itemsByCase.get(q.caseId).push(q);
  }
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

export const allTags = (section) => {
  const t = new Set();
  for (const q of state.questions) {
    if (section && sectionOf(q) !== section) continue;
    for (const x of q.tags || []) t.add(x);
  }
  return [...t].sort();
};

/** Sessions that actually carry questions for this section. */
export const sessionsIn = section =>
  state.sessions.filter(s =>
    state.questions.some(q => q.sessionId === s.id && sectionOf(q) === section));

// --- an unfinished run ----------------------------------------------------
//
// 午前Ⅱ is 40 minutes and survives in memory. 午後 is 150, read on a phone that
// will be backgrounded and may be killed; losing two hours of writing to a tab
// reload is not something to ask anyone to risk. The run is written back on
// every keystroke and every mark, and picked up from the home screen.

export const saveRun = run =>
  run ? db.put(db.STORES.kv, { ...run, savedAt: Date.now() }, 'run')
      : Promise.resolve();
export const loadRun = () => db.get(db.STORES.kv, 'run');
export const clearRun = () => db.del(db.STORES.kv, 'run');

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

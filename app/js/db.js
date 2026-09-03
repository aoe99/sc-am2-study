// IndexedDB wrapper. Holds the imported question data and the study record.
//
// The question data is copyrighted, so it never ships with the app: it is
// imported once from a file the user picks and lives only in this browser.

const DB_NAME = 'sc-am2';
const DB_VERSION = 1;

export const STORES = {
  kv: 'kv',                 // meta, import info
  questions: 'questions',   // keyPath id
  sessions: 'sessions',     // keyPath id
  assets: 'assets',         // keyPath path, value {path, blob}
  answers: 'answers',       // one record per answer, autoIncrement
  states: 'states',         // keyPath questionId — Leitner box, due date, tally
};

let dbPromise = null;

function open() {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORES.kv)) db.createObjectStore(STORES.kv);
      if (!db.objectStoreNames.contains(STORES.questions))
        db.createObjectStore(STORES.questions, { keyPath: 'id' });
      if (!db.objectStoreNames.contains(STORES.sessions))
        db.createObjectStore(STORES.sessions, { keyPath: 'id' });
      if (!db.objectStoreNames.contains(STORES.assets))
        db.createObjectStore(STORES.assets, { keyPath: 'path' });
      if (!db.objectStoreNames.contains(STORES.answers)) {
        const s = db.createObjectStore(STORES.answers,
          { keyPath: 'seq', autoIncrement: true });
        s.createIndex('questionId', 'questionId');
        s.createIndex('answeredAt', 'answeredAt');
      }
      if (!db.objectStoreNames.contains(STORES.states))
        db.createObjectStore(STORES.states, { keyPath: 'questionId' });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  return dbPromise;
}

function run(store, mode, fn) {
  return open().then(db => new Promise((resolve, reject) => {
    const tx = db.transaction(store, mode);
    const result = fn(tx.objectStore(store));
    tx.oncomplete = () => resolve(result && result.__value !== undefined
      ? result.__value : result);
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  }));
}

const wrap = req => {
  const box = {};
  req.onsuccess = () => { box.__value = req.result; };
  return box;
};

export const get = (store, key) => run(store, 'readonly', s => wrap(s.get(key)));
export const getAll = store => run(store, 'readonly', s => wrap(s.getAll()));
export const put = (store, value, key) =>
  run(store, 'readwrite', s => wrap(key === undefined ? s.put(value) : s.put(value, key)));
export const del = (store, key) => run(store, 'readwrite', s => wrap(s.delete(key)));
export const clear = store => run(store, 'readwrite', s => wrap(s.clear()));
export const count = store => run(store, 'readonly', s => wrap(s.count()));

/** Write many records in one transaction — importing 475 questions one at a
 *  time would open 475 transactions and take seconds on a phone. */
export function putMany(store, values) {
  return open().then(db => new Promise((resolve, reject) => {
    const tx = db.transaction(store, 'readwrite');
    const os = tx.objectStore(store);
    for (const v of values) os.put(v);
    tx.oncomplete = () => resolve(values.length);
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  }));
}

export function clearAll() {
  return open().then(db => new Promise((resolve, reject) => {
    const names = Object.values(STORES);
    const tx = db.transaction(names, 'readwrite');
    for (const n of names) tx.objectStore(n).clear();
    tx.oncomplete = resolve;
    tx.onerror = () => reject(tx.error);
  }));
}

/** Wipe the study record but keep the imported questions. */
export function clearProgress() {
  return open().then(db => new Promise((resolve, reject) => {
    const tx = db.transaction([STORES.answers, STORES.states], 'readwrite');
    tx.objectStore(STORES.answers).clear();
    tx.objectStore(STORES.states).clear();
    tx.oncomplete = resolve;
    tx.onerror = () => reject(tx.error);
  }));
}

/* What this browser remembers, and nothing else.
 *
 * Two workspaces live side by side and never mix: "own" (the householder's
 * home, files and results) and "demo" (whichever demo home is open). Each
 * keeps its own answers and its own last answer from the engine, so moving
 * between sections shows results at once, with no refitting.
 *
 * Nothing here is ever uploaded: it is the browser's own IndexedDB.
 */
const DB = "otwin-home";
const STORE = "state";
const KEY = "v2";
const OLD_KEY = "v1"; // the page before the sections existed

export const emptyWorkspace = () => ({
  answers: null,
  onboarded: false,
  weatherOk: false,
  files: [], // {id, name, bytes (ArrayBuffer), mapping}
  bills: [], // {id, kind, bill}
  home: null, // the header, the summary and the first estimate
  cards: null, // the data cards and the next best step
  report: null, // the last analysis
});

export const emptyState = () => ({
  version: 2,
  lang: (navigator.language || "en").toLowerCase().startsWith("es") ? "es" : "en",
  tab: "home",
  own: emptyWorkspace(),
  demo: { ...emptyWorkspace(), key: null },
});

let db = null;
function open() {
  return new Promise((resolve) => {
    try {
      const req = indexedDB.open(DB, 1);
      req.onupgradeneeded = () => req.result.createObjectStore(STORE);
      req.onsuccess = () => resolve((db = req.result));
      req.onerror = () => resolve(null);
    } catch {
      resolve(null); // a browser that keeps nothing: the page still works
    }
  });
}

async function tx(mode, fn) {
  const d = db || (await open());
  if (!d) return null;
  return new Promise((resolve) => {
    const t = d.transaction(STORE, mode);
    const r = fn(t.objectStore(STORE));
    t.oncomplete = () => resolve(r && r.result);
    t.onerror = () => resolve(null);
  });
}

/* The state of the previous page, if this browser has one. */
function migrate(old) {
  if (!old || !old.answers) return null;
  const state = emptyState();
  state.lang = old.lang || state.lang;
  const ws = {
    ...emptyWorkspace(),
    answers: old.answers,
    onboarded: !!old.onboarded,
    weatherOk: !!old.weatherOk,
    files: old.files || [],
    bills: old.bills || [],
  };
  if (old.example) {
    state.demo = { ...ws, files: [], bills: [], key: old.example };
    state.tab = "demo";
  } else {
    state.own = ws;
  }
  return state;
}

export async function load() {
  const saved = await tx("readonly", (s) => s.get(KEY));
  if (saved && saved.version === 2) return { ...emptyState(), ...saved };
  const old = await tx("readonly", (s) => s.get(OLD_KEY));
  return migrate(old);
}

export function save(state) {
  return tx("readwrite", (s) => s.put(state, KEY));
}

export function clearAll() {
  return tx("readwrite", (s) => {
    s.delete(KEY);
    s.delete(OLD_KEY);
  });
}

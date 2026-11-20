/* What this browser remembers, and nothing else.
 *
 * The householder may have several homes ("Piso de Madrid", "Casa del
 * pueblo"), each a workspace of its own: answers, files, results, the
 * simulations run on it. A home may have started from a demo (its files are
 * the demo home's own); it is a home like any other from then on. Moving
 * between homes shows results at once, with no refitting.
 *
 * Nothing here is ever uploaded: it is the browser's own IndexedDB.
 */
import { translate } from "./i18n";

const DB = "otwin-home";
const STORE = "state";
const KEY = "v3";
const OLD_KEYS = ["v2", "v1"]; // the page before several homes; before the sections

export const emptyWorkspace = () => ({
  answers: null,
  onboarded: false,
  weatherOk: false,
  files: [], // {id, name, bytes (ArrayBuffer), mapping, kind, enabled}
  bills: [], // {id, kind, bill}
  home: null, // the header, the summary and the first estimate
  cards: null, // the data cards and what to do next
  report: null, // the last fit
  stale: false, // the files changed since the last fit
  demo: null, // the demo home this one started from, if any
  demoTouched: false, // its files or answers changed since: the baked fit no longer applies
  simulation: null, // {baseline, scenarios}
});

export const newId = () => `h${Date.now().toString(36)}${Math.random().toString(36).slice(2, 5)}`;

/* One of the householder's homes: a workspace with a name of its own. */
export const emptyHome = (name) => ({ ...emptyWorkspace(), id: newId(), name });

export const emptyState = () => ({
  version: 3,
  lang: (navigator.language || "en").toLowerCase().startsWith("es") ? "es" : "en",
  route: "main", // the launch page, or "home"
  page: "home", // the page open inside "home"
  homes: [], // the householder's homes, in the order they were added
  current: null, // the id of the home being looked at
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

/* The state of an earlier page, brought to this one. */
function migrate(old) {
  if (!old) return null;
  const state = emptyState();
  state.lang = old.lang || state.lang;
  if (old.version === 2) {
    if (old.own?.answers) {
      const home = { ...emptyWorkspace(), ...old.own, id: newId(), name: translate(state.lang, "home_default_name") };
      state.homes = [home];
      state.current = home.id;
      state.route = "home";
    }
    return state;
  }
  if (!old.answers || old.example) return null; // v1 with nothing of the householder's own
  const home = {
    ...emptyWorkspace(),
    id: newId(),
    name: translate(state.lang, "home_default_name"),
    answers: old.answers,
    onboarded: !!old.onboarded,
    weatherOk: !!old.weatherOk,
    files: old.files || [],
    bills: old.bills || [],
  };
  state.homes = [home];
  state.current = home.id;
  state.route = "home";
  return state;
}

export async function load() {
  const saved = await tx("readonly", (s) => s.get(KEY));
  if (saved && saved.version === 3) {
    const state = { ...emptyState(), ...saved };
    delete state.demo; // the separate demo section, gone: demos live inside "My home"
    if (state.route === "demo") state.route = "main";
    state.homes = state.homes.map((h) => ({ ...emptyWorkspace(), ...h }));
    return state;
  }
  for (const key of OLD_KEYS) {
    const old = await tx("readonly", (s) => s.get(key));
    const state = migrate(old);
    if (state) return state;
  }
  return null;
}

export function save(state) {
  return tx("readwrite", (s) => s.put(state, KEY));
}

export function clearAll() {
  return tx("readwrite", (s) => {
    s.delete(KEY);
    for (const key of OLD_KEYS) s.delete(key);
  });
}

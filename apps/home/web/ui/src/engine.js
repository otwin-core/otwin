/* The page's handle on the engine (web/py/webmain.py, untouched).
 *
 * The engine keeps one session: the files it has read. The page has two
 * workspaces, so before anything is asked of the engine the session is made
 * to match the workspace asking: the demo's sample files, or the
 * householder's own files from this browser. Whatever a section already
 * knows (its last analysis) is kept by the page, so changing section shows
 * it at once and the engine is only needed again to read or fit something.
 */
let loadedFor = null; // which workspace the session holds
let mode = "page";

export const engineMode = () => mode;

export async function start(onStatus) {
  const info = await window.OtwinHome.start(onStatus);
  mode = info.mode;
  return info;
}

export function call(func, payload, bytes) {
  return window.OtwinHome.call(func, payload || {}, bytes);
}

/* One job at a time.
 *
 * The engine is single-threaded, and a job is several calls (read these
 * five files; fit this home). Letting two jobs interleave would fit a home
 * on half-read data and then fit it again. Everything that touches the
 * engine goes through here, in the order it was asked for.
 */
let queue = Promise.resolve();

export function serial(job) {
  const run = queue.then(job, job);
  queue = run.then(
    () => undefined,
    (error) => {
      // a job that fails must not be silent, and must not stop the queue
      console.error("Otwin Home: a job did not finish", error);
    },
  );
  return run;
}

export async function setLanguage(lang) {
  await call("set_language", { lang });
}

/* Forget which workspace the session holds (after a reset, say). */
export function invalidate() {
  loadedFor = null;
}

/* Make the engine's session the one `id` needs, and say what it read.
 *
 * `spec` is {demo: key} or {files, bills, timezone}. Returns the engine's
 * description of every file, by id.
 */
export async function useWorkspace(id, spec) {
  if (loadedFor === id && !spec.force) return null;
  loadedFor = null;
  await call("forget");
  const summaries = new Map();
  if (spec.demo) {
    const out = await call("load_samples", { sample: spec.demo });
    for (const f of out.files) summaries.set(f.id, f);
    loadedFor = id;
    return { summaries, answers: out.answers };
  }
  const tz = spec.timezone || "Europe/Madrid";
  for (const f of spec.files || []) {
    let out = await call(
      "read_file",
      { file_id: f.id, name: f.name, timezone_name: tz },
      new Uint8Array(f.bytes),
    );
    if (f.mapping && out.status === "needs_mapping") {
      out = await call("map_file", { file_id: f.id, mapping: f.mapping, timezone_name: tz });
    }
    summaries.set(f.id, out);
  }
  for (const b of spec.bills || []) {
    summaries.set(
      b.id,
      await call("add_bill", { file_id: b.id, kind: b.kind, bill: b.bill, timezone_name: tz }),
    );
  }
  loadedFor = id;
  return { summaries };
}

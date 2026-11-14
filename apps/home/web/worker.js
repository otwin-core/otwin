/* The engine's own thread, used when the site is served over http(s).
 *
 * Calibration fits a month of hours and takes tens of seconds; here it runs
 * off the page's thread, so the wizard stays responsive and its timer keeps
 * ticking. Messages in: {type: "boot"} and {type: "call", id, func, payload,
 * bytes}. Messages out: status, ready, boot-error, result, error.
 */
"use strict";

importScripts("runtime.js", "assets/manifest.js");

let booting = null;

function boot() {
  postMessage({ type: "status", text: "loading the engine (about 33 MB, once) ..." });
  importScripts("pyodide.asm.js", "pyodide.js", ...OTWIN_ASSET_SCRIPTS);
  return OtwinHomeCore.boot((text) => postMessage({ type: "status", text }));
}

self.onmessage = async (event) => {
  const m = event.data;
  if (m.type === "boot") {
    try {
      booting = booting || boot();
      const timings = await booting;
      postMessage({ type: "ready", timings });
    } catch (e) {
      postMessage({ type: "boot-error", message: String((e && e.message) || e) });
    }
  } else if (m.type === "call") {
    try {
      await booting;
      const result = OtwinHomeCore.call(m.func, m.payload, m.bytes);
      postMessage({ type: "result", id: m.id, result });
    } catch (e) {
      postMessage({ type: "error", id: m.id, message: String((e && e.message) || e) });
    }
  }
};

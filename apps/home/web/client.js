/* The page's handle on the engine: one API, two places it may run.
 *
 * Served over http(s) (GitHub Pages, any static server), the engine runs in
 * a Web Worker (worker.js) and the page stays responsive. Opened from
 * file://, where workers are forbidden, it runs on the page itself, loaded
 * by classic script tags. Either way:
 *
 *   await OtwinHome.start(status => ...);
 *   const out = await OtwinHome.call("read_file", {file_id, name}, bytes);
 */
"use strict";

const OtwinHome = (() => {
  let ready = null;
  let worker = null;
  let nextId = 1;
  let statusCb = () => {};
  const pending = new Map();

  const canUseWorker = () =>
    (location.protocol === "http:" || location.protocol === "https:") &&
    typeof Worker !== "undefined";

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = () => reject(new Error(`could not load ${src}`));
      document.head.appendChild(s);
    });
  }

  async function startOnPage() {
    statusCb("loading the engine ...");
    for (const src of ["pyodide.asm.js", "pyodide.js", "runtime.js", "assets/manifest.js"]) {
      await loadScript(src);
    }
    for (const src of OTWIN_ASSET_SCRIPTS) await loadScript(src);
    const timings = await OtwinHomeCore.boot(statusCb);
    return { mode: "page", timings };
  }

  function startWorker() {
    return new Promise((resolve, reject) => {
      try {
        worker = new Worker("worker.js");
      } catch (e) {
        reject(e);
        return;
      }
      worker.onmessage = (event) => {
        const m = event.data;
        if (m.type === "status") statusCb(m.text);
        else if (m.type === "ready") resolve({ mode: "worker", timings: m.timings });
        else if (m.type === "boot-error") reject(new Error(m.message));
        else if (m.type === "result" || m.type === "error") {
          const p = pending.get(m.id);
          pending.delete(m.id);
          if (m.type === "result") p.resolve(m.result);
          else p.reject(new Error(m.message));
        }
      };
      worker.onerror = (e) => reject(new Error(e.message || "the engine failed to start"));
      worker.postMessage({ type: "boot" });
    });
  }

  function start(onStatus) {
    if (onStatus) statusCb = onStatus;
    if (!ready) {
      // Some embedded browsers (an editor's preview pane) serve over http but
      // refuse workers; the page itself can always run the engine.
      ready = canUseWorker()
        ? startWorker().catch((e) => {
            if (worker) worker.terminate();
            worker = null;
            console.warn(`Otwin Home: no worker (${e.message}); running on the page`);
            return startOnPage();
          })
        : startOnPage();
    }
    return ready;
  }

  async function call(func, payload, bytes) {
    await start();
    if (!worker) {
      await new Promise((r) => setTimeout(r, 30)); // let the page paint first
      return OtwinHomeCore.call(func, payload, bytes);
    }
    return new Promise((resolve, reject) => {
      const id = nextId++;
      pending.set(id, { resolve, reject });
      const transfer = bytes ? [bytes.buffer] : [];
      worker.postMessage({ type: "call", id, func, payload: payload || {}, bytes }, transfer);
    });
  }

  return {
    start,
    call,
    get mode() {
      return worker ? "worker" : "page";
    },
  };
})();

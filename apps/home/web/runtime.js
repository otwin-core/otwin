/* The computation core of Otwin Home: Python (Pyodide) running the twin.
 *
 * Runs wherever it is loaded: inside worker.js when the site is served over
 * http(s) (GitHub Pages), or on the page itself when it is opened from
 * file://, which forbids workers. Either way it is classic scripts only,
 * because that is all a file:// page may load. The binary assets (engine
 * wasm, stdlib, NumPy and SciPy wheels, the app's code) arrive embedded as
 * base64 through otwinRegisterAsset, and a fetch shim serves them from
 * memory: nothing is downloaded at run time, and nothing is uploaded, ever.
 *
 *   await OtwinHomeCore.boot(status => ...);
 *   OtwinHomeCore.call("read_file", {file_id, name}, bytes);  // JSON in, JSON out
 */
"use strict";

const OtwinHomeCore = (() => {
  const registry = new Map(); // asset name -> Uint8Array
  const timings = {};
  let pyodide = null;
  let dispatcher = null;

  function registerAsset(name, b64) {
    const raw = atob(b64);
    const bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
    registry.set(name, bytes);
  }

  function installFetchShim() {
    const realFetch = typeof fetch === "undefined" ? null : fetch.bind(globalThis);
    globalThis.fetch = async (input, init) => {
      const url = String(input instanceof Request ? input.url : input);
      const name = url.split("/").pop().split("?")[0];
      if (registry.has(name)) {
        const bytes = registry.get(name);
        const type = name.endsWith(".wasm")
          ? "application/wasm"
          : name.endsWith(".json")
            ? "application/json"
            : "application/octet-stream";
        return new Response(new Blob([bytes], { type }), {
          status: 200,
          headers: { "Content-Type": type, "Content-Length": String(bytes.length) },
        });
      }
      if (url.startsWith("file:") || !realFetch) {
        throw new TypeError(`offline bundle: no embedded asset for ${url}`);
      }
      return realFetch(input, init);
    };
  }

  async function boot(onStatus) {
    const say = onStatus || (() => {});
    const t0 = performance.now();
    const mark = (name) => {
      timings[name] = Math.round(performance.now() - t0);
    };
    if (typeof loadPyodide !== "function" || typeof _createPyodideModule !== "function") {
      throw new Error("pyodide.js and pyodide.asm.js must be loaded first");
    }
    installFetchShim();
    say("starting Python ...");
    pyodide = await loadPyodide({ indexURL: "./" });
    mark("pyodide_ready_ms");
    say("loading NumPy and SciPy ...");
    await pyodide.loadPackage(["numpy", "scipy"], { messageCallback: () => {} });
    mark("packages_ready_ms");
    say("loading the twin ...");
    pyodide.unpackArchive(registry.get("app.zip"), "zip", { extractDir: "/app" });
    pyodide.runPython('import sys; sys.path.insert(0, "/app"); import webmain');
    dispatcher = pyodide.runPython(
      "import json, webmain\n" +
        "lambda f, p, d=None: json.dumps(webmain.dispatch(f, json.loads(p), d))",
    );
    mark("app_ready_ms");
    registry.clear(); // the bytes now live inside Python
    return timings;
  }

  /* Call a function of web/py/webmain.py: keyword arguments as JSON, and,
   * for a file, its bytes (a Uint8Array) handed to Python without a copy. */
  function call(func, payload, bytes) {
    if (!dispatcher) throw new Error("the engine is not ready yet");
    const args = JSON.stringify(payload || {});
    const out = bytes ? dispatcher(func, args, bytes) : dispatcher(func, args);
    return JSON.parse(out);
  }

  return { boot, call, timings, registerAsset };
})();

/* Called by the generated asset scripts in dist/assets/. */
function otwinRegisterAsset(name, b64) {
  OtwinHomeCore.registerAsset(name, b64);
}

# The browser runtime: decision record

**Decision: Pyodide (CPython on WebAssembly) running the unchanged Python
code, on the page's own thread, as a fully embedded single-folder bundle.**
The Rust engine compiled to wasm32 stays on the table as a later accelerator
for simulation only, never for fitting.

## The requirement that decided it

The twin must calibrate and simulate from a static page opened from
`file://` with the network disabled. A `file://` page in a default browser
may load **classic `<script>` tags and nothing else**: `fetch()` and
`XMLHttpRequest` of local files are blocked (opaque origin), ES modules and
dynamic `import()` are blocked by the same CORS rule, and dedicated workers
cannot be started. Whatever the runtime, every byte must therefore arrive
embedded in classic scripts, and the engine must be instantiated from bytes
in memory. Both candidates can be packaged that way; the question is what
runs inside.

## The candidates (DESIGN.md §5)

**A. Pyodide + the pure-Python `otwin` + the Otwin Home packages.**
Everything that is tested runs unchanged: the compiler, the NumPy backend,
`fit_parameters` with its identifiability checks, the calibration report,
the scenarios and tariffs. The browser shows the same numbers as
`pytest apps/home`, to the digit. Cost: a ~41 MB bundle and NumPy-backend
speed.

**B. `otwin-core` (Rust) compiled to `wasm32-unknown-unknown`.** Verified in
this evaluation: the crate compiles for that target as it is (rayon links;
only the unused `simulate_batch` would fail at runtime), and the engine is
a few hundred kB — a hundred times smaller and roughly ten times faster
than A for stepping. But the engine only *integrates a lowered model*.
Model building, input and schedule handling, the hourly meter, least
squares in log-parameters, identifiability, the plain-language report, the
scenarios and the tariffs are all Python. Choosing B means rewriting the
twin layer in JavaScript: thousands of lines, a second implementation of
code whose whole value is that it is tested against closed forms, and a
standing parity burden. That is the "import, do not rewrite" rule
(ROADMAP rule 2) applied to our own code.

**C. A + the PyO3 engine built for Pyodide (emscripten).** The upgrade path
if A's runtime hurts: same Python everywhere, Rust stepping underneath. Not
needed at today's numbers (below); it would not shrink the bundle.

## How A is packaged for file:// (the spike)

`build_bundle.py` writes `dist/`: `pyodide.asm.js` and `pyodide.js` loaded
as classic scripts (Pyodide 0.28.3, the newest line that ships a classic
loader; the 314.x line is ES-module only and cannot start from `file://`);
the wasm, stdlib, lock file, NumPy/SciPy wheels and the app code embedded
as base64 in classic scripts; a `fetch` shim serving those from memory; and
the IANA time-zone database (`tzdata`) packed in, because Pyodide ships
none and every schedule and tariff here lives in Europe/Madrid. Workers
being unavailable on `file://`, computation runs on the page's thread; a
hosted copy of the same bundle could move it to a worker unchanged.

## Measured (this machine: Apple Silicon, Chrome, file://, network off)

| What | Chrome | Firefox |
| --- | --- | --- |
| Bundle on disk (`dist/`) | 41.3 MB (30.2 MB of assets, base64-inflated) | same |
| Scripts parsed + assets decoded (to `boot()` start) | 184 ms | 362 ms |
| Pyodide engine started | 889 ms | 1 034 ms |
| NumPy + SciPy loaded | 1 775 ms | 2 236 ms |
| App imported (first `import otwin`) | 2 196 ms | 2 760 ms |
| Synthetic month (truth simulation, 5-min steps) | 2.4 s | 4.3 s |
| **Calibration** (31 days hourly, 4 parameters, with identifiability) | 18.2 s | 33.4 s |
| Five scenarios (baseline + 5 cases, billed) | 1.6 s | 3.3 s |
| Whole page, first byte to results on screen | 24.6 s | 44.2 s |
| Same work natively (CPython 3.14, same NumPy backend) | calibrate 15 s, scenarios 0.9 s | — |

Pyodide costs only ~1.2× native Chrome-side (~2.2× in Firefox), because the
hot loop is the same NumPy backend either way. The results — the calibration
verdict, every finding and all five scenario sentences — are identical to
the native run to the digit.

Verified by `verify_offline.py`: a real Chrome, `context.set_offline(True)`,
and every request the page makes is `file://` (counted and asserted).

## What would reopen the decision

* Calibration beyond ~2 minutes on a mid-range phone → build the PyO3
  engine wheel for Pyodide (option C) and keep everything else unchanged.
* Instant what-if sliders in the UI → option B *for simulation only*,
  loading the lowered IR JSON exported from the calibrated Python model.
* Pyodide dropping the classic loader in all maintained lines → revisit
  the single-file packaging (the fetch shim already isolates us from most
  of the loader's details).

## Addendum: the wizard, served (2026-11-14)

The same bundle now also serves the wizard from a static server (GitHub
Pages). Served over http(s), the engine moves into a Web Worker
(`worker.js` loads the same classic scripts with `importScripts`), so the
~20 s calibration no longer freezes the page; from `file://` it stays on
the page's thread as before. Measured with `verify_wizard.py` in Chrome on
this machine:

| | static server (worker) | `file://` (page) |
| --- | --- | --- |
| Step 1 on screen | 0.1 s | 1.5 s |
| Engine ready | 3.0 s | 2.7 s |
| Calibration of the sample month | 19.9 s | 19.5 s |
| Requests leaving the server / the disk | 0 of 17 | 0 of 16 |

The worker costs nothing in speed; it buys a responsive page. The one
network request the wizard can make is the optional weather fetch, which
the householder starts and which sends only the province's coordinates and
the dates to Open-Meteo.

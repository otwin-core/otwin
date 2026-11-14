# Otwin Home in the browser: the wizard

A static site that turns a household's own files into a calibrated digital
twin, entirely client-side. Three steps:

1. **Your home** — selectors only: province, kind, size, age, heating,
   air conditioning, thermostat habits, people, hot water, appliances. No
   physics is typed in; `survey` turns the answers into a twin with typical
   values, and the page shows what it assumed.
2. **Your data** — drop the files the household already has (Datadis or
   distributor electricity, Open-Meteo weather, Shelly or Tapo plugs, Home
   Assistant, gas and water bills). A CSV in any other layout gets the
   column mapper: pick which column is the time, which the values, what
   they are and their unit; the page pre-fills its best guess. No weather
   file? One button fetches it from Open-Meteo, sending only the province's
   coordinates and the dates.
3. **Calibration** — one click fits the twin to the month and shows the
   plain-language report (good / usable / not enough data), with a chart of
   the meter against the twin, day by day.

**Files never leave the browser**, and the page says so at the top. They
are read into the engine's memory in this tab; there is no server and no
upload. The engine is the runtime chosen in [DECISION.md](DECISION.md):
Pyodide running the repository's tested Python, unchanged.

## Build, serve, deploy

```bash
python apps/home/web/build_bundle.py            # assets cached once; dist/ ≈ 41 MB
python -m http.server -d apps/home/web/dist     # any static server works
```

`dist/` is a plain static site: relative paths, no server-side anything, a
`.nojekyll`. To publish it on GitHub Pages, set *Settings → Pages → Source*
to "GitHub Actions" and run the **Otwin Home site** workflow
(`.github/workflows/home-pages.yml`, manual on purpose). Opening
`dist/index.html` straight from disk also works, offline.

## Where the engine runs

| Opened from | Engine | Why |
| --- | --- | --- |
| a static server (Pages, `http.server`) | a Web Worker | calibration takes ~20 s; the page stays responsive and its timer ticks |
| `file://` | the page's own thread | browsers forbid workers on `file://`; same code, same results |

Step 1 renders at once from `questions.js` (baked from `survey.QUESTIONS`
at build time) while the engine loads in the background (~3 s from a local
server, plus the first download of ~33 MB over the network; cached after).

## Proving it

```bash
pip install playwright
python apps/home/web/verify_wizard.py --formats   # the wizard, served, in Chrome
python apps/home/web/verify_wizard.py --file      # the same, from file://
python apps/home/web/verify_offline.py            # demo.html, file://, network off
```

`verify_wizard.py` serves `dist/`, answers step 1 with the sample home,
drops the sample electricity CSV and the weather-station CSV (whose layout
no parser knows: the mapper's guess is checked, then confirmed), calibrates,
and asserts that no request leaves the local server. `--formats` first
drops every ingest test fixture at once and prints how each was read.

## What is what

| File | Role |
| --- | --- |
| `index.html`, `style.css`, `wizard.js` | the wizard: plain HTML, Helvetica, vanilla JS |
| `client.js` | the page's handle on the engine: worker when served, page thread from disk |
| `worker.js` | the engine's thread |
| `runtime.js` | the engine core: embedded assets, `fetch` shim, Pyodide, `dispatch` |
| `py/webmain.py` | the wizard's session in Python: read, map, judge, calibrate |
| `samples/` | a January from a known home (`make_samples.py` regenerates it) |
| `demo.html` | the earlier end-to-end demonstration: calibration and five what-ifs |
| `build_bundle.py` | writes `dist/` |
| `verify_wizard.py`, `verify_offline.py` | the browser proofs |

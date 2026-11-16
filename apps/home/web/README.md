# Otwin Home in the browser: the page

A static site that turns a household's own files into a model of its home,
entirely client-side, in English and Spanish (the selector at the top; a
first visit follows the browser's language).

## Four sections, each on its own

| Section | What lives there |
| --- | --- |
| **Your home** | The householder's own home: the questions on a first visit, then the dashboard with their files and results. |
| **Demo** | Homes whose answer we already know, with their own data. Everything demo lives here, and nothing of it touches "Your home". |
| **Simulation** | Where predictions will go (empty for now, on purpose). |
| **Help** | What this is, what happens to your data, how to get your data, what the words mean. |

"Your home" and "Demo" each keep their own answers, files and last analysis
in this browser. The engine has one session, so opening a section points it
at that section's workspace; whatever the section already knows is shown at
once, and the engine is only needed again to read or fit something.

## The dashboard, in both sections

* **The answer, always current**: how well the home keeps the heat (the
  energy certificate's A-G scale, *not* an official certificate), euros a
  month, and how sure we are (reliable / approximate / we need more data),
  with a line saying what changed after each addition.
* **The next best step**: the one thing that would help most now.
* **The data as cards**: electricity, gas, water, thermometer, weather.
  Files can be dropped anywhere on the page and land in the right card; gas
  and water bills can be typed in; the weather is fetched from Open-Meteo
  once it is allowed.
* **Five areas**: where the money goes, your heating, what if, can I trust
  it (the hidden-month test), and over the months.

**Nothing to press**: adding or removing data, or editing the home,
analyses it again by itself. Served, the engine has its own thread and the
hidden-month test runs by itself too; opened from disk, it waits for a
click, so the page never freezes for long unasked.

## How it is built

The page is React (`ui/`), built by Vite into **one classic script**
(`app.js`) with its CSS beside it (`app.css`). That is not a style choice:
a browser refuses `<script type="module">` from `file://`, where this page
must still work. `index.html` is a hand-written shell that loads the baked
questions, the build stamp, the engine's loader and then the page, all with
plain `<script src>`; it hands their `const` globals to the bundle.

Radix primitives give the behaviour (tabs, radio groups, checkboxes,
select, dialog, accordion) with no styles of their own; the look is in
`ui/src/styles.css`: Bauhaus, which is to say Helvetica, black on white,
red for what matters, blue and yellow for the rest, squares and circles,
thick rules, no rounded corners and no shadows.

The engine (`py/`, and the Python packages it carries) is not touched by
any of this: physics stays apart.

**Files never leave the browser**, and the page says so at the top. They
are read into the engine's memory in this tab; there is no server and no
upload. The engine is the runtime chosen in [DECISION.md](DECISION.md):
Pyodide running the repository's tested Python, unchanged.

## Build, serve, deploy

```bash
python apps/home/web/build_bundle.py            # builds ui/ with Vite too; dist/ ≈ 42 MB
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
python apps/home/web/verify_wizard.py --gas 15dic-15ene   # the gas home, any period
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
| `index.html` | the shell: classic scripts, the no-JavaScript note, the "not built yet" guard |
| `ui/src/App.jsx` | the four sections, the language, what is dropped where |
| `ui/src/useHome.js` | one home: its files, its analysis, one engine job at a time |
| `ui/src/store.js`, `ui/src/engine.js` | what this browser remembers; the handle on the engine |
| `ui/src/parts/` | the screens: onboarding, dashboard, cards, explore, demo, simulation, help |
| `ui/src/styles.css` | the Bauhaus look |
| `ui/src/i18n.js` | every word the page shows, English and Spanish |
| `py/texts.py` | every sentence the engine writes, English and Spanish |
| `client.js` | the page's handle on the engine: worker when served, page thread from disk |
| `worker.js` | the engine's thread |
| `runtime.js` | the engine core: embedded assets, `fetch` shim, Pyodide, `dispatch` |
| `py/webmain.py` | the session in Python: read, map, cards, analyse, report, the hidden-month test |
| `samples/` | a January from a known all-electric home, and `gas_home/` with three winter periods (15 Oct–15 Nov, 15 Dec–15 Jan, 15 Feb–15 Mar) of electricity, gas bill, water bill and weather; `make_samples.py` regenerates them |
| `demo.html` | the earlier end-to-end demonstration: calibration and five what-ifs |
| `build_bundle.py` | writes `dist/` |
| `verify_wizard.py`, `verify_offline.py` | the browser proofs |

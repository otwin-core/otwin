# Otwin Home: changelog

All notable changes to Otwin Home (`apps/home`). Dates are the sessions'.

## 2026-11-20

### Added
- Simulation inside "Your digital home", shown only once the model is built:
  the next twelve months on an average year's weather, "as it is today" and
  up to three changes made with the home's own controls (heating system and
  power, temperatures, night setback, air conditioning, insulation, hot
  water, people, appliances, prices), each a monthly curve in euros or kWh
  with its uncertainty band and a yearly total against today.
- Climate normals for every province (`survey/climate.py`) and the sun
  through the windows as a calendar-following input of the twin.
- D3 charts for every curve: real axes, zoom, crosshair, legend focus,
  gradient bands; the twin blue, measured data black.
- Uncertainty bands: the fit's daily electricity and every forecast month,
  from the measured conductances and always-on load moved by their own
  uncertainty.
- Shared controls: temperature gauges (16–26 °C, 22–28 °C, half degrees),
  sliders (m², year built, people, kW, prices), switches, three-way and
  row selectors; the engine accepts numbers beside the old names.
- Demo homes inside "My home" (gas flat, all-electric flat): a home whose
  bills are its own, built at once from the baked fit (`adopt_fit`).
- `ARCHITECTURE.md`, this changelog.

### Changed
- "Calibration" is "Your digital home": a didactic intro, five steps in the
  order that matters, a result card with one short line and the action,
  "Build / Update my digital home" as explicit buttons, "Reset".
- The fit's charts (meter against twin, indoor temperature) sit under the
  verdict on the digital-home page.

### Removed
- The separate Demo route and door, the demo bills on the steps, the old
  demo page (`web/demo.html`, `verify_offline.py`, `run_example`), the data
  cards, the Explore tabs, and the design notes (`DESIGN.md`,
  `WORKFLOW.md`, `components/COMPONENTS.md`, `web/DECISION.md`,
  `web/README.md`; what mattered is in `ARCHITECTURE.md`).

## 2026-11-19

### Added
- A guardrail comparing the bills with the home described (a typical
  January's use); warnings in plain words.
- Short "what is missing" lines with the step to go to.

### Changed
- Building the model is a decision: nothing is fitted by itself; files
  changed since the last build are flagged.

## 2026-11-18

### Added
- Bills as PDF or photo, read in the page: pdf.js for the text layer,
  PaddleOCR on ONNX Runtime Web for scans and photos (`ocr/engine.js`),
  photo straightening, a rule-based field reader (`ingest/invoice.py`),
  a review form with the words each field was read from.
- Electricity bills as a kind of their own (what electricity really cost).
- The "Your digital home" checklist with undo per step and inline help.

## 2026-11-17

### Added
- The heating's nameplate power as an answer, kept as given in the fit.
- The monthly bill beside the house; one bar per fuel with its uses.
- The house drawing: month and outdoor temperature outside, indoor inside;
  the energy the heating drew, with the detail behind an info button.

### Changed
- People give 70 W of sensible heat and are home half the time; the samples
  were regenerated accordingly.
- The heat shown as lost is the model's own zone loss (fabric, radiation,
  air), not UA × ΔT.

## 2026-11-16

### Added
- Several named homes; a settings dialog behind a gear; a launch page with
  routes and breadcrumbs.
- A traffic light instead of the A–G letter; the house drawn in SVG with
  pictograms of our own; the demos baked at build time (`demos.js`).

### Fixed
- File buffers detached when switching homes; empty homes left behind;
  parallel removals overwriting each other.

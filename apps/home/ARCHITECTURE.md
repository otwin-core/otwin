# Otwin Home: architecture

Otwin Home is a static site with a physics engine inside it. The page is
React; the engine is the repository's own Python, running unchanged in the
browser on Pyodide; the two talk through one JSON function call. Nothing is
uploaded, there is no server, and the page works offline and from `file://`.

```
browser
├── the page (web/ui, React → one classic script app.js)
│   ├── routes: Main → My home → Your digital home → Simulation; Help; the gear
│   ├── useHome.js: one home's files, fit and simulations; one engine job at a time
│   ├── ocr/engine.js: pdf.js text layer; PaddleOCR on ONNX Runtime Web for scans and photos
│   ├── parts/controls.jsx: gauge, slider, switch, three-way, row (questions and simulation alike)
│   └── parts/charts/D3Chart.jsx: every curve, with bands, zoom and crosshair
├── the engine (web/client.js → worker.js or the page thread → runtime.js → Pyodide)
│   └── web/py/webmain.py: the session (files, fit, report, forecast), texts.py (en, es)
└── the Python it carries (app.zip): ingest, components, survey, calibration, scenarios, otwin
```

## The engine's layers

**Ingest** (`ingest/`). Every parser takes a file's bytes and returns
`Series`: one quantity on one channel, UTC intervals or instants, SI values,
a real/estimated flag. Formats: Datadis JSON, CNMC and distributor CSVs
(e-distribución, i-DE, UFD), Shelly and Tapo exports, Home Assistant
statistics and history, gas and water bills (CSV, or typed in), Open-Meteo
JSON and CSV, and `ColumnMap` for anything else (`describe_csv` guesses the
columns; a thermometer's or a weather station's log is read with the guess
when it is confident, or when the householder said what the file is).
`invoice.py` reads a bill's *fields* from words with positions, whatever
produced them: utility, supplier, period, kWh, m³, Fc, PCS, readings,
amount, each with a confidence and the snippet it came from. Rules, no
model: a lexicon, dates in numbers or words, decimal commas, OCR slips.

**Components** (`components/`). The home as Otwin components, one module per
role, so a home compiles into the same port-Hamiltonian model as any other
Otwin system and runs on the NumPy or the Rust backend. Temperatures are
kelvin.

| Module | Role | Components |
| --- | --- | --- |
| `boundaries` | temperatures the home does not control | `Outdoors`, `Setpoint` |
| `stores` | where heat accumulates | `RoomAir`, `BuildingFabric`, `StoredWater` |
| `exchanges` | heat flows down ΔT, each conductance fittable | `Envelope`, `Ventilation`, `InteriorSurface`, `StandbyLoss`, `SkyRadiation` |
| `gains` | heat pushed in | `Appliance`, `BaseLoad` (metered); `Occupants`, `SolarGain` (free); `HotWaterDraw` (heat out) |
| `machines` | fuel ↔ heat under a thermostat, with a meter | `Boiler`, `ElectricHeater`, `HeatPump`, `AirConditioner`, `WaterHeater` |
| `zones` | the heated space assembled | `ThermalZone` (1R1C or 2R2C), outputs `heat_loss`, `radiation_loss` |
| `schedules` | the clock-driven inputs | `Schedule` (24 or 168 local-hour values), `ClimateSchedule` (follows the calendar) |

Two distinctions carry the design. *Metered or free*: only appliances and
machines show on a meter; people and the sun do not, and leaving them out
makes a fit blame the heating for heat it never supplied. *Parameter or
input*: what the house is (conductances, capacities, machine power, base
load) is fitted; what happens to it (weather, sun, appliance use, draws,
setpoints) is an input, from a schedule or from measured data.

**Survey** (`survey/`). `HomeDescription` is the answers; `build_twin` makes
a twin with typical values from them: envelope conductance by era and
exposure, 0.45 W/K·m² of ventilation, the heating's nameplate kW when
given (kept as given, never fitted) or a typical size, people as 70 W of
sensible heat each present half the time (all night, one in four by day),
the sun through the windows as an effective aperture of 4.5 % of the floor
on the province's typical irradiance. Answers may be numbers (m², a year,
20.5 °C) or the older names. `climate.py` holds each province's typical
year: monthly means on seven climate shapes anchored to the province's
January, the daily swing, and the solar radiation of its band, shaped hour
by hour. `example.py` makes the demo homes' files from a twin with known
"true" parameters, so a fit can be checked against the truth.

**Calibration** (`calibration/`). `calibrate(twin, HourlyData)` fits what
the meters can see: the envelope's and the air's conductances, how long the
home keeps its warmth, the heating's size, the always-on load, and the
thermometer's offset when there is one; gas bills are fitted as period
totals when the heating runs on gas. Each number comes with its uncertainty
and a verdict (good within ±10 %, usable within ±30 %, not enough data
otherwise, with the reason). Several periods are fitted together, each
with its own spin-up.

**Scenarios** (`scenarios/`). What-ifs on a calibrated twin over the period
it was calibrated on, billed on Spanish tariffs (2.0TD periods, power term,
taxes; gas by m³ × Fc × PCS). The page's "Improvements" come from here.

**The session** (`web/py/webmain.py`). What the page calls: read a file,
map its columns, add a bill (typed, or read from a document), the first
estimate from the answers alone (`home`), the cards and the guardrail
(`cards`: a bill under a third or over three times a typical January's is
flagged as probably another home's), the fit (`analyse`) and its report in
either language (`report`), the flows the house is drawn from, the twelve-
month forecast (`forecast`), and `adopt_fit` for a demo home whose fit was
baked at build time. Every sentence comes from `texts.py` in English and
Spanish.

## The page

**Routes.** `Main` (one door) → `My home` → `Your digital home` →
`Simulation`; `Help` from the breadcrumb bar; the gear holds the language,
the homes and "delete everything". The launch page is never more than two
clicks away. State lives in IndexedDB (`store.js`): several homes, each
with its answers, files (bytes), bills, last fit, simulations, and whether
it started from a demo.

**One home** (`useHome.js`). The engine has one session; opening a home
points it at that home's files. Reading files, fitting and simulating are
engine jobs run one at a time (`engine.serial`); a job must never wait on
another job. Building the model is a button, not a side effect: a change
marks the home stale and offers "Update my digital home". A demo home is
built at once from the fit baked into `demos.js` and the engine adopts it,
until any file or answer is touched.

**Reading bills.** A PDF with a text layer is read exactly with pdf.js. A
scan or a photo goes to PaddleOCR's PP-OCRv4 detector and PP-OCRv3 Latin
recogniser on ONNX Runtime Web; long lines are split at ink-free columns and
stretched 1.5× before recognition (otherwise "660" collapses to "60"); a
photo can be straightened by dragging four corners. Models and runtime are
embedded in `ocr-assets.js` and loaded on first use. Fields are prefilled
and checked by the householder before the bill counts.

**Charts** (`D3Chart.jsx`). The twin is always blue; what was measured is
black; changes are red, ochre and grey. The band is the twin with its
measured conductances and always-on load moved by their own uncertainty,
down and up, drawn as a gradient strongest at the centre and 10 % at the
edges. Real axes, zoom on the dates, a crosshair, and a legend that focuses
one curve.

## Where the engine runs

Pyodide was chosen over a server, a Rust-to-wasm port and a JavaScript
rewrite because the engine's tested Python runs unchanged, nothing leaves
the browser, and the page works from disk. Served over http(s) the engine
runs in a Web Worker so the page stays responsive; from `file://`, where
workers are forbidden, on the page itself. Every binary asset (engine wasm,
stdlib, wheels, the app's code, the OCR models) arrives embedded as base64
in classic scripts and is served from memory by a `fetch` shim: nothing is
fetched at run time. The page is one IIFE bundle because `file://` refuses
ES modules. Cost: about 90 MB of static files, a 3 s start when served.

## Choices worth knowing

- **The grade.** The engine grades the envelope on the energy certificate's
  A–G thresholds (W/K per m² of floor); the page never shows the letter,
  only a traffic light (green A–C, orange D–E, red F–G), because it is not
  an official certificate.
- **Energy balance.** The house shows what the heating drew from the meter
  and, behind an info button, the heat delivered, the other heat generated
  inside and the losses (fabric with its radiation to the sky, air). In ISO
  13790's terms Q_ht = Q_H,nd + η·Q_gn: what leaves equals the heating plus
  the utilised gains, up to what the fabric stores.
- **Meters as integrals.** Meter energy is the integral of each step's
  midpoint output, exactly what the implicit midpoint rule applies, so the
  heat balance closes to rounding; a thermometer reads instants.
- **An appliance's heat** goes all indoors or all outside (a dishwasher
  draining hot water); a COP and an EER are seasonal constants; the
  thermostat is the cycle average of an on/off controller.
- **Guardrail, not gatekeeping.** Bills far from what the home described
  would use are flagged in words, never refused.
- **Nothing silent.** A job that fails says so; a bill is never added
  without a look; the model is never fitted without a press.

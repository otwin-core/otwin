# Otwin Home: design survey

Otwin Home is a digital twin of one household's electricity, water and gas.
It is built from data the household already has: hourly smart-meter readings,
utility bills, cheap Wi-Fi smart plugs and the public weather record. It
calibrates itself, says how sure it is, and answers what-if questions: an
abnormal cold spell, better insulation, one more person living in the house. It
runs entirely in the browser, and the household's data never leaves the
device. The user needs to know what a kWh and a m³ are, and nothing more.

This document is the survey that ROADMAP rule 1 requires before any code is
written. It covers who already does this, what Otwin has and lacks for a home,
which files a Spanish household can actually export today and in what shape,
and where the twin can run client-side. It should be posted as a Discussion
under *Ideas & Architecture* before implementation starts.

Status: survey, plus the ingest layer (§4.0) in `apps/home/ingest`, the
home component library (§3) in `apps/home/components`, calibration from
one month of hourly electricity in `apps/home/calibration`, what-if
scenarios billed against the household's tariff in `apps/home/scenarios`,
and the three-step browser wizard in `apps/home/web` (survey in
`apps/home/survey`).

---

## 1. Who already does this, and who relies on it

| Tool | What it does | What it does not do for this user |
| --- | --- | --- |
| EnergyPlus, TRNSYS, IDA ICE | Detailed building simulation | Needs geometry, constructions and an engineer. No calibration from meter data out of the box. |
| Modelica Buildings library (LBNL), IDEAS, AixLib | Component building models in Modelica | Engineering tool. Could be imported as an FMU (ROADMAP phase 8) but is far larger than a 2-state home model. |
| ISO 52016-1 / ISO 13790 5R1C hourly method; `RC_BuildingSimulator` (Python) | The standard simplified resistance-capacitance (RC) zone model | Forward model only, parameters from the building description. No fit to bills, no uncertainty. |
| CE3X, HULC, CYPETHERM (Spanish energy performance certificate, *certificado energético*) | Rates a dwelling from its description | Produces a label, not a twin. Ignores the actual meter. |
| Home Assistant Energy dashboard | Collects and plots meter and plug energy | Records data. No physical model, no forecast, no scenarios. **We read its exports (§4.4).** |
| Datadis viewers, distributor portals, `homeassistant-edata` | Show and download Datadis hourly data | Plots and tariff comparison. No physics. **We read their files (§4.1).** |
| CNMC tariff simulator | Prices a year of hourly consumption under each tariff | Cost only. **Its CSV format is the de facto standard we accept (§4.1).** |
| Sense, Emporia, Neurio and similar | Load disaggregation from a clamp meter | Paid hardware and cloud. No thermal model. |
| Energy-signature / degree-day regression (PRISM, ASHRAE Guideline 14) | Fits heating energy against outdoor temperature | Static. Cannot answer a cold *spell* with thermal inertia or a setpoint change. **This is our baseline: the twin must beat it to earn its place.** |

Nothing in that list connects a household's own meters to a calibrated
physical model, gives forecasts with measured coverage, and refuses a scenario
that the data does not support. That is the gap Otwin fills (ROADMAP, "Where
Otwin sits"). Rule 2 applies: the RC zone is not new physics, so Otwin builds
it from existing primitives and checks it against the ISO 52016 closed form
rather than inventing its own.

---

## 2. The twin in one picture

```
          outdoor air (Open-Meteo, hourly)            sun (Open-Meteo)
                    │                                      │
             r_inf (ventilation)                      × aperture A_sol
                    │                                      │
   heating ──► [ indoor air C_air ] ◄── internal gains ◄───┘
   (gas × η                │            (plug + base electricity,
    or elec × COP)       r_af            occupants × 80–100 W)
                           │
                  [ walls/floor C_fab ] ── r_fo ── outdoor air
```

The house is two heat stores (indoor air and the building fabric) and three
heat paths to outside. Heating, sun, appliances and people put heat in. The
weather sets the outside temperature. Hot water and appliances are energy
bookkeeping on top of that, not dynamics (§3.2).

Five numbers describe the thermal part: `C_air`, `C_fab`, `r_af`, `r_fo` and
`r_inf`. Three more describe how fuel becomes heat: the boiler efficiency η or
heat-pump COP, the solar aperture, and the base electrical load. The user only
sees the derived quantities: heat loss in W/K (UA = 1/r), the time the house
takes to cool by 1 °C, and € per heating day.

**Checked in this survey:** that model compiles today from existing
components only (`ThermalMass` ×2, `ThermalResistance` ×3, `Ambient(None)`,
`HeatSource(None)`). Its inputs are `outside` and `heating`, and its five
fittable parameters are `air.capacity`, `fabric.capacity`, `r_af.resistance`,
`r_fo.resistance` and `r_inf.resistance`. One year at hourly steps with the
implicit midpoint rule takes **323 ms on the NumPy backend** (CPython 3.14,
Apple silicon). §5 uses that number.

---

## 3. Mapping Otwin components to a home

### 3.1 What exists and maps directly

| Home element | Otwin component | Notes |
| --- | --- | --- |
| Indoor air and furniture | `ThermalMass(capacity)` | State is stored heat; output `temperature`. |
| Walls, floor, roof (thermal inertia) | `ThermalMass` | Second store; makes the 2R2C model. |
| Envelope heat loss (UA) | `ThermalResistance(1/UA)` or `Convection(UA)` | Both are fittable parameters. |
| Ventilation and infiltration | `ThermalResistance` | Separate from the fabric path so "seal the windows" is one parameter. |
| Outdoor temperature | `Ambient(temperature=None)` | An input on every step, fed from Open-Meteo. |
| Heating delivered | `HeatSource(heat=None)` | An input on every step. |
| Internal gains | `HeatSource(None)` | Appliance electricity ends up as heat inside the house. |
| Domestic hot-water cylinder (*termo*) | `ThermalMass` + `ThermalResistance` to the room + `HeatSource` (draw) | Only for houses with an electric *termo*. A smart plug on it gives an excellent signal. |
| Rooftop cistern (*aljibe*, *depósito*) | `Tank` + `Orifice`/`Pipe` + `FlowSource` | Only where one exists. Most flats have none, so water is accounting (§3.2). |
| Parameter fitting | `otwin.hybrid.fit_parameters` | Least squares in log-parameters; returns sensitivities. |
| "Does the data determine this?" | `otwin.estimate.identifiability` (called by `fit_parameters`) | Central for homes: bills alone rarely identify `C_fab`. |
| Indoor temperature estimate | `ExtendedKalmanFilter`, `EnergyConsistentObserver` | Only useful with an indoor thermometer (§4.7). |
| Forecast with measured coverage | `forecast.evaluate`, `horizon_conformal`, `ConformalBand` | Forecasts next week's or month's kWh and m³ as a range with a stated coverage. |
| Baselines the twin must beat | `forecast.baselines` (`seasonal_naive`, `persistence`) | Plus the degree-day signature (§1), which is missing. |
| Refusal outside the data | `advise.Envelope`, `Verdict` | "Cold spell at −8 °C" when the record never went below 0 °C gets a refusal with the reason, or a stated extrapolation fraction. |
| Gap handling | `signal.resample`, `find_gaps`, `coverage` | Plugs go offline; Datadis has estimated hours. |
| Provenance | `interfaces.TwinManifest`, `Provenance` | Records which files the twin was calibrated on. |
| Unit normalisation | `io.source.to_si`, `normalise` | Has W, kWh, Wh, degC, K. Missing m³ and L (§3.3). |

### 3.2 What maps, but is bookkeeping rather than a component

- **Appliance loads.** Otwin's electrical domain models circuits (V, I). A
  household's electricity is a set of metered energies:
  `total = base load + Σ plugs + heating electricity + unexplained`. That is a
  balance between time series, not a circuit, and it should not be forced into
  `Resistor`s. The plugs enter the thermal model as internal gains. The
  unexplained remainder is reported, never hidden.
- **Water.** Monthly or two-monthly m³ is the sum of per-person use, a fixed
  household use and any leak. The physics that matters is hot water, which
  links water to gas or electricity through `ρ c V ΔT`. The mains-water
  temperature changes with the season and is derived from outdoor
  temperature.
- **Occupants.** Each person adds about 80–100 W of body heat while at home,
  plus their share of hot water and appliance use. Most households have the
  same number of occupants for the whole record, so the data cannot separate
  "per person" from "per house". The identifiability report will say so.
  Per-person figures (IDAE averages, entered by the user) are then labelled
  as *assumptions*, never as fitted results.

### 3.3 What is missing

Listed in the order they block work. **Core** items change `src/otwin` and
follow rules 1 and 7: a survey, then a conformance case in otwin-spec with a
deliberately wrong variant. **App** items stay in `apps/home`.

| # | Gap | Where | Why it blocks |
| --- | --- | --- | --- |
| G1 | **Measurements that are integrals over an interval.** `fit_parameters` compares outputs at instants `t`. Meters report energy *per interval*: kWh per hour, kWh per bill period, m³ per two months. Bill periods are irregular (28–65 days) and overlap the hourly grid. | core; **hourly bridged in the app** | For hourly electricity, `calibration.HourlyMeter` presents the compiled home to `fit_parameters` as a model whose output is the exact hourly mean (outputs at each sub-step's midpoint state with its held input, averaged per hour), so the engine's own fit and identifiability run unchanged. Irregular bill periods (gas, water) still need the core form: `measurements={"heating.heat": IntervalSeries(starts, ends, energy)}`, compared against the integral of the output over each interval. |
| G2 | **A source scaled by a fittable parameter.** Heat delivered = η × gas power, and solar gain = aperture × irradiance, where η and the aperture are unknowns and the gas power and irradiance are inputs. `HeatSource(None)` takes the input as given. | core | η and the solar aperture are among the most useful parameters to fit. A `gain=` parameter on `HeatSource` is the smallest change. |
| G3 | **Units m³, L, m³/h, and gas kWh from m³.** `to_si` has neither m³ nor L. A Spanish gas bill converts `kWh = m³ × Fc × PCS` (§4.5). | core (units), app (conversion) | Water and gas readings cannot be normalised. |
| G4 | **Heat-pump COP depending on temperature.** COP falls as the outdoor temperature drops. It is not a lossless two-port, so it does not belong in `Transformer`. | app first | Needed only for houses with a heat pump or air-conditioning split (*bomba de calor*, *aire acondicionado*). Start as an app-side input transform with a tabulated COP(T_out). Move it to core only if a second user needs it. |
| G5 | **Thermostat (setpoint control).** Scenarios ask what heat is needed to hold 20 °C, which is a feedback loop. | app, **done** | Built without a step loop: a thermostat's time-averaged output `clip(P/band · (T_set − T), 0, P)` is a monotone, dissipative law between a setpoint reservoir (`Ambient`) and the heated body, so it compiles as an ordinary resistor (`components.Thermostat`). The setpoint is a parameter or an input (schedules). |
| G6 | **Degree-day / energy-signature baseline.** | app | ROADMAP's "does the physics earn its place" test needs the static model as a baseline. It is a 2-parameter regression. |
| G7 | **Local-time, DST-aware interval parsing.** Spanish files use local time with 23- and 25-hour days. `signal.resample` works on float seconds and does not know about time zones. | app | Every parser must convert to UTC interval bounds first (§4.0). |
| G8 | **A calibration audit and decision record** (ROADMAP phase 7, next items). | core, in progress | Home Otwin uses them when they land. It must not build its own. |

Not missing: nonlinear algebraic networks (ROADMAP phase 4) are not needed,
because every node in the home model is pinned by a thermal store.

---

## 4. Data a Spanish household can export today

### 4.0 One internal shape for everything

Implemented in `apps/home/ingest` (see its README). Every parser produces
the same columnar shape, and nothing downstream sees a vendor format:

```
Series(
    quantity: str,         # one of ingest.QUANTITIES, e.g. "electricity_import",
                           # "plug_energy", "gas_energy", "gas_volume", "water_volume",
                           # "outdoor_temperature", "solar_irradiance", "gas_cost"
    channel:  str,         # CUPS (Spanish supply-point code), plug name, HA entity, "gas"
    kind:     "interval" | "mean" | "instant",
    start:    int64[n],    # UTC seconds; interval start, inclusive
    end:      int64[n],    # UTC seconds; interval end, exclusive (== start for instants)
    value:    float64[n],  # SI: J, m^3, K, W, W/m^2, EUR
    quality:  int8[n],     # REAL (0) or ESTIMATED (1), as the file said
    source:   str,         # file name (plus "#sheet" for workbooks)
)
```

Energies, volumes and money are **intervals** (the total over
`[start, end)`), temperatures are **instants**, and Open-Meteo irradiance or
Home Assistant hourly temperatures are **means** over an interval. Keeping
`start`/`end` explicit is what makes G1 and G7 tractable. Readings the file
marks as estimated keep that mark, so the fit can weight them lower and the
report can say how many there were. A `Series` is read-only, and building
one validates it: values are finite, sorted, non-overlapping, never negative
where that is impossible, and **plausible for a household**. Checking that
the average power or the temperature range is plausible is what catches a
Wh file read as kWh, or °C read as K.

**Parser contract:** each parser is a pure function
`bytes → list[Series]`, and `ingest.load()` picks one from the file's
contents, never its name. A malformed file raises `IngestError` naming the
file, the line (or JSON record, or spreadsheet row) and the offending
column, for example
`consumo.csv: line 14: column 'Consumo_kWh': '0,2x7' is not a number`. A
CSV no parser recognises is refused with its columns listed, and
`ingest.ColumnMap` + `ingest.parse_mapped` read it once the user says which
column is what. Real files are private, so the shapes below come from public
documentation and public samples, each marked with how sure we are of it.
The tests use synthetic fixtures built from a known truth
(`apps/home/tests/fixtures/make_fixtures.py`).

### 4.1 Electricity: hourly smart-meter data (Datadis and distributor portals)

Every Spanish supply point under 15 kW has had a remotely read meter since
2019. The distributor, not the retailer, holds the hourly curve. Datadis
(datadis.es) is the joint platform of the distributors and is the one
download point for all of them. Distributor codes: 1 Viesgo, 2 e-distribución
(Endesa), 3 E-Redes, 4 ASEME, 5 UFD (Naturgy), 6 EOSA, 7 CIDE, 8 i-DE
(Iberdrola). Since the move to quarter-hour settlement, Datadis also serves
15-minute data (`measurementType=1`).

**(a) Datadis private API, JSON.** Confidence: high; seen in several
independent open-source clients.

```
GET https://datadis.es/api-private/api/get-consumption-data
    ?cups=ES0021…&distributorCode=8&startDate=2025/01&endDate=2025/12
    &measurementType=0&pointType=5
[
  {"cups": "ES0021…", "date": "2025/01/01", "time": "01:00",
   "consumptionKWh": 0.231, "obtainMethod": "Real",
   "surplusEnergyKWh": 0.0, "generationEnergyKWh": 0.0,
   "selfConsumptionEnergyKWh": 0.0},
  …
]
```

- Dates are month-granular (`YYYY/MM`). Requests that start in the partial
  month when the contract began have been reported to return HTTP 500.
- `consumptionKWh` is **energy imported from the grid**, not the home's total
  use. With rooftop solar, total use = import + self-consumption.
- **The hour label convention is disputed.** One client documents `"02:00"`
  as the hour starting at 02:00, while the CNMC CSV below uses 1–24 for the
  hour *ending*. The parser must not guess. It reads the convention from the
  data (a `24:00` or `24` means hour-ending), and the parser tests include
  both conventions plus a 23-hour March day and a 25-hour October day.
- The API needs the user's NIF (Spanish tax ID) and password, is rate-limited,
  lags by several days, and cannot be called from a browser page on another
  origin (no CORS). **Version 1 therefore accepts the downloaded file and
  never asks for credentials.** An API path, if ever added, belongs in the
  optional local helper (§6).

**(b) Datadis web download.** The private area offers XML, CSV or JSON, sent
later by e-mail ("DATADIS - Descarga de información disponible"). The JSON is
the API shape above. The CSV header could not be confirmed from public
sources; a real anonymised export is needed to pin it (§7, Q1).

**(c) CNMC-standard CSV, used by most distributor portals.** Confidence:
high for the column set; separators and the decimal mark vary.

```
CUPS;Fecha;Hora;Consumo_kWh;Metodo_obtencion
ES00XXXXXXXXXXXXXXDB;06/09/2015;1;0,267;R
```

- `;` separator, `,` decimal mark, `Fecha` as `dd/mm/yyyy`, `Hora` 1–24
  (hour ending), `Metodo_obtencion` `R` (real) or `E` (estimated). This is
  the minimum the CNMC simulator accepts, so many tools emit it.
- UFD (Naturgy) emits the same columns with the header `Consumo`.

**(d) e-distribución (Endesa) CSV.** Confidence: medium; public samples from
2020.

```
CUPS;Fecha;Hora;AE_kWh;AS_KWh;AE_AUTOCONS_kWh;REAL/ESTIMADO
ES0031…;01/07/2020;1;0,423;0;;R
```

`AE` is active energy imported, `AS` is exported (solar surplus), and
`AE_AUTOCONS` is self-consumed. The variant
`CUPS;Data;Hora;AE_kWh;LECTURA REAL/ESTIMADA` also exists.

**(e) i-DE (Iberdrola) CSV.** Confidence: medium; a different layout, public
samples from 2020.

```
CUPS;FECHA-HORA;INV / VER;CONSUMO Wh;GENERACION Wh;
ES0021…;2020/09/01 01:00;1;161;0;
```

The values are in **Wh**, not kWh. Date and hour share one column. `INV / VER`
(winter/summer time flag) is what tells the two 02:00 hours of the October
change apart. It must be read, not dropped.

**Accept rule:** the electricity parser identifies the variant by its
header. It accepts `dd/mm/yyyy`, `yyyy/mm/dd` and `yyyy-mm-dd`, hours 0–23,
1–24 and `HH:MM`, kWh or Wh by the column name, and `;` or `,` separators
(the decimal mark is then whatever the separator is not). An unrecognised
header is a refusal that names the closest known variant.

### 4.2 Smart plugs: TP-Link Tapo class

Tapo P110/P115 plugs (firmware 1.1.2 or later, app 2.10 or later) can export
from the app. Confidence: medium; from TP-Link community posts.

- The export is an **Excel workbook** sent by e-mail, with sheets covering
  the last 7 days at 1-hour resolution, the last 3 months at 1-day
  resolution, and the last 12 months at 1-month resolution. Each row has a
  date/time and *Energy Usage (kWh)*. A power sheet has 5-minute watts
  (`2023/05/16 14:55:00  164`), which are **instantaneous readings, not
  energy**.
- **Hourly data is kept for only 7 days.** To keep hourly resolution, the
  user has to export every week, so the app merges overlapping workbooks and
  removes duplicates by interval. Older months survive only as daily totals,
  and the fit treats them as interval measurements (G1).
- The workbook is read by a ~150-line standard-library reader
  (`ingest/_xlsx.py`: cell values only, member sizes capped), so `openpyxl`
  is not a dependency. The CSV that the third-party TapoPanel tool writes
  can be read with `ingest.ColumnMap` until a sample justifies a dedicated
  parser.
- Local-API libraries exist, but `python-kasa` is GPL-3.0 and so cannot be
  vendored (CONTRIBUTING, "Dependency licence policy"). It is not needed.

### 4.3 Smart plugs and meters: Shelly, local API

Shelly devices answer HTTP on the local network without a cloud account.
Confidence: high for the API, which is documented by the vendor.

| Device class | What to read | Shape |
| --- | --- | --- |
| Gen2+/Gen3 plugs (Plus Plug S, Plug S Gen3) | `GET http://<ip>/rpc/Switch.GetStatus?id=0` | `{"apower": W, "aenergy": {"total": Wh, "by_minute": [mWh, mWh, mWh], "minute_ts": unix}, …}`. **No stored history**, so it must be polled (§6). |
| Gen2+ single-phase meters (Pro EM, EM Gen3, Pro EM-50) | `GET http://<ip>/em1data/<id>/data.csv?add_keys=true&ts=…&end_ts=…` | CSV with a header when `add_keys=true`. One row per stored interval, with a unix timestamp and active energy per interval in Wh. History is kept for weeks (about 60 days on a Pro 3EM). |
| Gen2+ three-phase meters (Pro 3EM) | `GET http://<ip>/emdata/<id>/data.csv?add_keys=true` | As above, per phase. |
| Gen1 Shelly EM | `GET http://<ip>/emeter/0/em_data.csv` | Older CSV layout. |
| Gen1 Plug S | `GET http://<ip>/meter/0` | `total` is in **watt-minutes**, not Wh: divide by 60. |

`<id>` is the component instance (0 or 1), **not** the device MAC. Devices
with authentication use HTTP digest. The exact CSV column names come from the
EMData/EM1Data documentation; a captured file is needed to pin them.

### 4.4 Home Assistant energy export

Many households that own plugs already run Home Assistant, which is then the
easiest way in: one export covers every plug, the meter and any thermometer.
Confidence: high.

- **Long-term statistics** are written once per hour and kept indefinitely.
  Energy sensors store `state` and `sum`, and the hourly energy is the
  difference between consecutive `sum` values, which survives meter resets.
  Measurement sensors, such as thermometers, store `mean`, `min` and `max`.
- **Export routes, in order of preference:**
  1. The `homeassistant-statistics` custom integration (`export_statistics`
     action): CSV/TSV with columns
     `statistic_id, start, unit, mean, min, max, sum, state` (+ `delta`), or
     JSON. `start` is the hour start.
  2. The built-in `recorder.get_statistics` action, with `period: hour`
     and `types: [sum, state, mean]`, returns JSON. The user copies it into
     the app from the developer tools.
  3. The History panel's *Download data* (2024.2+): CSV with
     `entity_id,state,last_changed`, holding raw state changes. Usable for
     cumulative energy sensors by differencing, with gaps flagged.
- The unit comes from the `unit` column (`kWh`, `Wh`, `m³`, `°C`). It is
  never assumed.

### 4.5 Gas bills

Datadis covers electricity only, and remotely read gas meters are rare in
Spanish homes. Gas comes as a bill, roughly every two months, and is often
**estimated** between real readings. The distributors are Nedgia, Madrileña
Red de Gas, Nortegas and Redexis.

The bill prints everything needed, and the app asks for exactly that:

| Field | Example | Note |
| --- | --- | --- |
| Period start, end | 2025-01-08 → 2025-03-07 | Irregular. Becomes an interval measurement (G1). |
| Reading start, end (m³) | 10 412 → 10 655 | Also gives the m³ consumed. |
| Reading type | real / estimada | Estimated periods are weighted down. |
| Conversion factor Fc | 0.98 | Pressure and altitude correction, printed on the bill. **Never assumed**: it varies with the town's altitude. |
| PCS (kWh/m³) | 11.72 | Gross calorific value, printed on the bill, varies by month. |
| kWh billed | 2 791 | `= m³ × Fc × PCS`. The app checks this equality and points out an inconsistency instead of silently picking one value. |
| Tariff (RL.1/RL.2/RL.3), € fixed, € per kWh | | Only for costing scenarios. |

Accepted shapes: a form, or a CSV with those columns
(`inicio;fin;lectura_inicio_m3;lectura_fin_m3;tipo;fc;pcs_kwh_m3;kwh;importe_eur`),
one row per bill. PDF bill extraction is **not** in version 1: layouts differ
by retailer and change often, so a wrong number read from a PDF would be
worse than typing it in. It can be revisited later as an assisted entry,
with the user confirming each field.

### 4.6 Water bills

Water is municipal, with one operator per town (Canal de Isabel II in Madrid,
Aigües de Barcelona, Emasesa, …). Bills come every one, two or three months
and are priced in consumption blocks. The same row shape as gas, without Fc
and PCS:
`inicio;fin;lectura_inicio_m3;lectura_fin_m3;tipo;importe_eur`.
Some operators offer remotely read meters with daily data in their portals,
but the formats differ and none was confirmed in this survey, so they are
accepted later through a generic `date;m3` CSV.

### 4.7 Indoor temperature (optional, strongly recommended)

A €10–25 Wi-Fi or Bluetooth thermometer (Shelly H&T, or any sensor in Home
Assistant) turns the model from "fitted to energy only" into "fitted to energy
and the state it drives". Without it, the identifiability check is expected
to mark `C_fab` and the split between `r_fo` and `r_inf` as not determined
from monthly gas bills. It enters through the HA export (§4.4) or the
generic CSV `timestamp;°C`.

### 4.8 Weather: Open-Meteo

Confidence: high; the vendor documentation was checked during this survey.

```
GET https://archive-api.open-meteo.com/v1/archive
    ?latitude=40.42&longitude=-3.70&start_date=2025-01-01&end_date=2025-12-31
    &hourly=temperature_2m,shortwave_radiation,wind_speed_10m
    &timeformat=unixtime&timezone=Europe%2FMadrid
{ "latitude": 40.4, "longitude": -3.7, "utc_offset_seconds": 3600,
  "timezone": "Europe/Madrid", "hourly_units": {"temperature_2m": "°C", …},
  "hourly": {"time": [1735686000, …], "temperature_2m": [4.1, …], …} }
```

- **Always request `timeformat=unixtime`.** Open-Meteo applies the UTC offset
  in effect *at request time* to the whole response and ignores DST changes
  inside the range, so ISO local times are an hour off on one side of every
  change. Unix time has no such problem.
- `temperature_2m` is instantaneous at the timestamp. `shortwave_radiation`
  is the mean over the **preceding** hour, so `start = t − 3600`.
- The archive (reanalysis) lags by about 5 days. The most recent days come
  from the forecast API (`api.open-meteo.com/v1/forecast?past_days=…`), and
  each reading is tagged with which API it came from.
- It works from the browser (CORS allowed) and needs no key. It is free for
  non-commercial use within published rate limits, and the data is CC BY 4.0:
  the app shows the attribution.
- Only latitude and longitude are sent. The app asks for a postcode or a
  point on a map, rounds the position to about 1 km, and never sends the CUPS
  or an address.

### 4.9 Prices (for cost scenarios)

Version 1 uses the prices the user types in from the bill: the 2.0TD period
prices (P1/P2/P3), fixed charges, and gas €/kWh. The 2.0TD period of each hour
depends on hour, weekday and national holidays, and is computed locally. Hourly
regulated prices (PVPC) from Red Eléctrica (REE) are an optional later step:
the public `apidatos.ree.es` needs no token, while ESIOS does.

---

## 5. Running the twin in the browser

The requirement is that everything runs client-side: no server, and no
upload of a CUPS, an address or a consumption curve. Four candidates were
considered.

| | Candidate | What runs | Reuse of checked code | Cost |
| --- | --- | --- | --- | --- |
| **A** | **Pyodide** (CPython on WebAssembly) running the pure-Python `otwin` wheel with the NumPy backend | Everything: `compile`, `fit_parameters`, `identifiability`, conformal bands, `Envelope` | **All of it.** The `otwin` wheel is pure Python, and NumPy and SciPy ship with Pyodide. | Tens of MB on first load, then cached. CPU-bound Python is typically 1.5–3× slower than native. |
| **B** | `otwin-core` compiled to `wasm32-unknown-unknown` with `wasm-bindgen`, called from JavaScript | Simulation only, from lowered IR JSON (`PHSIR.lower()`) produced at build time. Parameters are symbolic, so `set_params` re-parameterises without recompiling. | The engine only. Fitting, identifiability, conformal bands and the envelope would have to be **rewritten in JS**, which goes against rules 2 and 4. | Small (hundreds of kB) and fast. `rayon` (used only by `simulate_batch`) has to be feature-gated off. |
| **C** | **A + `otwin-engine` built for Pyodide** (`wasm32-unknown-emscripten`, which maturin and pyodide-build support for PyO3) | As A, with `RustBackend` doing the time stepping | All of it, plus the Rust engine. NumPy/Rust parity is already tested. | A separate CI target and the same `rayon` gating. Only worth doing if A is too slow. |
| D | PyScript or JupyterLite | Pyodide underneath | Same as A | PyScript only adds a layer over A. JupyterLite is a notebook, the wrong interface for a non-engineer. Rejected. |

**Measured (the spike in `apps/home/web`, see its DECISION.md).** A 41 MB
fully embedded bundle starts Python in under a second, loads NumPy and SciPy
in under two, calibrates the example home's month in 18 s on Chrome (33 s on
Firefox) against 15 s natively on the same NumPy backend, and runs five
billed scenarios in 1.6 s. Verdicts, findings and sentences match the native
run to the digit, from a `file://` page with the network off.

**Decision: A, measured and shipped as the computation core in
`apps/home/web` (its DECISION.md records the reasons); C if a phone-class
device hurts; B never for fitting.**

- A reuses the checked code unchanged, so the twin in the browser gives the
  same numbers as `pip install otwin`.
- The app logic (`apps/home/ingest` and what follows it) is plain Python. It is tested with
  pytest on CPython and loaded unchanged in Pyodide, so there is one codebase
  and no JS reimplementation of any number.
- B stays available for a later instant "drag the insulation slider" view,
  limited to simulating a model already fitted by A.
- Licences: Pyodide is MPL-2.0. It is a runtime that the web page loads, not
  a dependency of the `otwin` package, so the CONTRIBUTING rule ("MPL may be
  optional") is respected. This is stated in the app's NOTICE.

**Browser constraints that shape the design:**
- An HTTPS page cannot call `http://192.168.x.x`. Mixed-content blocking and
  Chrome's Private Network Access forbid it, and Shelly does not send CORS
  headers. **The browser app cannot poll plugs directly.** Live plug data
  arrives through file exports, Home Assistant, or the optional helper (§6).
- Data persists in IndexedDB in the user's browser. Export and import of the
  whole household as one `.otwin-home.json` file serve as backup and as the
  way to move to another device.
- The computation runs in a Web Worker so the page stays responsive.

---

## 6. Install and privacy

- **Install:** none. A static site (HTML, JS and the app's Python files) on
  GitHub Pages. "Install" means opening a URL, and the site works offline
  once cached (PWA manifest). A downloadable zip of the same site serves
  people who want to run it from disk.
- **Optional local helper**, for hourly plug history only: a single Python
  script that polls Shelly plugs every few minutes and writes the generic
  CSV. It is not required for any feature, and Home Assistant users never
  need it.
- **Personal data:** a CUPS is personal data under the GDPR, and so is an
  hourly curve. Neither leaves the device. The only outbound requests are to
  Open-Meteo (rounded coordinates) and, if enabled, REE prices. The app
  lists every outbound request on its *Privacy* page.
- **Language:** Spanish and English from the first screen. Units are always
  kWh, m³, °C and € per month; SI values are internal only.

---

## 7. Risks and open questions

| # | Question | How it gets settled |
| --- | --- | --- |
| Q1 | Real header of the Datadis CSV and XML web exports, and today's e-distribución and i-DE layouts (§4.1 b, d, e) | Before the parsers are final: one anonymised export from each, with CUPS and dates shifted. Parsers are tested against synthetic files of that exact shape (rule 6). |
| Q2 | Datadis hour-label convention (start vs end) | Read from the data (§4.1). Cross-checked by summing a bill period against the bill. |
| Q3 | Tapo workbook sheet and column names (§4.2) | One real export. |
| Q4 | Whether monthly gas bills plus hourly electricity identify more than UA and η | The calibration answers it with `identifiability`. The expected answer is no for `C_fab`, and the UI must say "add a thermometer" rather than show a number. |
| Q5 | Pyodide fit time on a phone (§5) | Measured in Pyodide. It decides between A and C. |
| Q6 | G1 and G2 are core changes | Each needs its own rule-1 note and an otwin-spec conformance case. If core review takes longer, the app carries a temporary wrapper that is deleted when core lands. |
| Q7 | Houses with rooftop solar | `consumptionKWh` is import only (§4.1 a). Version 1 asks "do you have solar?" and, if so, requires the export and self-consumption columns or refuses the heating fit. |

---

## Sources consulted in this survey

- Datadis API, from open-source clients: [ctr-datadis](https://pypi.org/project/ctr-datadis/),
  [MrMarble/datadis](https://github.com/MrMarble/datadis),
  [go-datadis](https://pkg.go.dev/github.com/rubiojr/go-datadis),
  [beedis](https://github.com/BeeGroup-cimne/beedis),
  [datadis-exporter](https://github.com/rare-magma/datadis-exporter),
  [homeassistant-edata issue #152](https://github.com/uvejota/homeassistant-edata/issues/152);
  [Iberdrola on Datadis](https://www.iberdrolaespana.com/about-us/business-lines/smart-grids-spain/datadis)
- Distributor CSV formats: [CNMC simulator announcement](https://blog.cnmc.es/2015/10/29/nuevo-simulador-para-controlar-la-factura-de-la-luz-con-contador-inteligente/),
  [simuladorfacturaluz.es, CSV formats](https://www.simuladorfacturaluz.es/el-fichero-csv-de-consumos/),
  [nergiza forum](https://nergiza.com/foro/threads/interpretando-el-csv-de-tu-distribuidora-de-electricidad.334/),
  [energytricolor guide](https://energytricolor.com/curva-consumo-horario-e-distribucion-i-de/)
- Shelly: [EM1Data](https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/EM1Data/),
  [EMData](https://shelly-api-docs.shelly.cloud/gen2/0.14/ComponentsAndServices/EMData/),
  [shelly-emdata-sqlite](https://github.com/wimleers/shelly-emdata-sqlite),
  [community thread on stored data](https://community.shelly.cloud/topic/9522-how-do-you-recover-stored-data-from-pro-em-50/)
- Tapo: [TP-Link energy monitoring FAQ](https://www.tp-link.com/us/support/faq/3490/),
  [community: export and CSV](https://community.tp-link.com/en/home/forum/topic/609316),
  [community: data export](https://community.tp-link.com/en/smart-home/forum/topic/712002),
  [TapoPanel](https://www.obviousidea.com/windows-software/tapopanel/)
- Home Assistant: [recorder.get_statistics](https://www.home-assistant.io/actions/recorder.get_statistics/),
  [homeassistant-statistics](https://github.com/klausj1/homeassistant-statistics),
  [statistics generation explained](https://drcoolzic.github.io/ha-statistics-doc/doc/part2_statistics_generation/)
- Open-Meteo: [Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api),
  [Open-Meteo](https://open-meteo.com/)

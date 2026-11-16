# Otwin Home

A digital twin of one household's electricity, water and gas, built from data
the household already has. The design survey is in [DESIGN.md](DESIGN.md).

Otwin Home ships separately from the `otwin` package: nothing here is in the
wheel that `pip install otwin` installs.

## `ingest/`: household data files to one checked time series

Every parser takes the bytes of a file and returns a list of `ingest.Series`:
one quantity on one channel, as UTC intervals or instants, with values in SI
units and a real/estimated flag (DESIGN.md §4.0). It needs only the Python
standard library and NumPy, so it can run unchanged in the browser under
Pyodide. Nothing in it touches the network.

```python
import ingest

series = ingest.load(open("consumo.csv", "rb").read(), source="consumo.csv")
for s in series:
    print(s, s.values_in("kWh").sum())
```

`ingest.load()` recognises the format from the file's contents. A malformed
file raises `ingest.IngestError` naming the file, line and column:

```
consumo.csv: line 14: column 'Consumo_kWh': '0,2x7' is not a number
ide.csv: line 2: column 'CONSUMO kWh': 1553 kWh in 1 h is not plausible for a household; check the unit of this column
gas.csv: line 3: column 'kwh': 9999 kWh but m³ × Fc × PCS = 215 × 0.98 × 11.68 = 2461.0 kWh
```

| Format | Parser | Source of the shape | Confidence |
| --- | --- | --- | --- |
| Datadis JSON (API and web download) | `parse_datadis_json` | open-source Datadis clients | high |
| CNMC-standard CSV (`Consumo_kWh`; UFD `Consumo`) | `parse_distributor_csv` | CNMC simulator sample | high |
| e-distribución CSV (`AE_kWh;AS_KWh;AE_AUTOCONS_kWh`) | `parse_distributor_csv` | public samples (2020) | medium |
| i-DE CSV (`FECHA-HORA;INV / VER;CONSUMO Wh`) | `parse_ide_csv` | public samples (2020) | medium |
| Shelly EM1Data / EMData CSV (`add_keys=true`) | `parse_shelly_csv` | Shelly Gen2 API docs | high for the API, column names to confirm |
| Tapo P110/P115 app workbook (.xlsx) | `parse_tapo_xlsx` | TP-Link community descriptions | low: sheet and header names to confirm |
| Home Assistant long-term statistics (CSV/TSV) | `parse_ha_statistics` | `homeassistant-statistics` export | high |
| Home Assistant History CSV | `parse_ha_history` | HA History panel download | high |
| Gas bills, typed in (CSV) | `parse_gas_bills` | the bill's printed fields (DESIGN.md §4.5) | ours |
| Water bills, typed in (CSV) | `parse_water_bills` | the bill's printed fields (DESIGN.md §4.6) | ours |
| Open-Meteo JSON (API) | `parse_open_meteo_json` | Open-Meteo docs | high |
| Open-Meteo CSV (website download) | `parse_open_meteo_csv` | Open-Meteo docs | high |
| Anything else | `ColumnMap` + `parse_mapped`, with `describe_csv` to suggest a map | the user | — |

Choices worth knowing:

- **Hour numbers.** The convention is read from the data: hour 0 means
  hours are numbered from the start of the hour, and 24 or 25 means from the
  end. A file showing neither is refused until `hour_convention=` is given.
  Hours count elapsed time from local midnight, so the 23-hour March day and
  the 25-hour October day map exactly onto UTC.
- **i-DE's `INV / VER`** flag is read as the UTC offset of the label, so
  either way of writing the extra October hour decodes the same.
- **Open-Meteo local ISO times** are refused unless the response is in UTC,
  because Open-Meteo applies one offset to the whole range. Download with
  `timeformat=unixtime`.
- **Decimal comma** files may write meter readings with a thousands dot
  (`10.412` m³ is 10 412 m³). A dot that cannot be a thousands separator in
  such a file (`0.267`) is refused rather than misread.
- **Gas and water bills** use meter-reading dates: a bill from 08/01 to 07/03
  covers local `[08/01, 07/03)`. Bills may not overlap. A bill's start
  reading must equal the previous bill's end reading when the two periods
  meet.
- **Overlapping exports** of the same thing (a Tapo workbook every week) are
  joined with `ingest.merge`. A repeated interval with the same value is
  dropped, and one with a different value is an error.

Not covered yet: the Datadis web *CSV* download (its header could not be
confirmed, DESIGN.md §7 Q1; if it uses the CNMC columns,
`parse_distributor_csv` already reads it), Shelly Gen1 `em_data.csv`, polled
Shelly `Switch.GetStatus` snapshots, Home Assistant `recorder.get_statistics`
responses, and PDF bills.

## `components/`: the home on the Otwin engine

One module per role, the way `otwin.components` keeps one module per domain;
the full schema is [components/COMPONENTS.md](components/COMPONENTS.md).
Every component plays one of Otwin's own roles, so a home compiles into the
same port-Hamiltonian model as a battery or a pump station and runs on the
NumPy or the Rust backend. Temperatures are kelvin.

| Module | Role | Components |
| --- | --- | --- |
| `boundaries` | temperatures the home does not control | `Outdoors` (the weather, an input), `Setpoint` (a dial: parameter or scheduled input) |
| `stores` | where heat accumulates | `RoomAir` (hours), `BuildingFabric` (days), `StoredWater` (litres) |
| `exchanges` | heat flows down ΔT, each conductance a fittable parameter | `Envelope`, `Ventilation`, `InteriorSurface`, `StandbyLoss` |
| `gains` | heat pushed in, no temperature of its own | `Appliance`/`BaseLoad` (metered), `Occupants`/`SolarGain` (free), `HotWaterDraw` (heat out) |
| `machines` | fuel ↔ heat under a thermostat, with a meter | `Boiler` (gas), `ElectricHeater`, `HeatPump` (COP), `AirConditioner` (EER), `WaterHeater`; the law is `Thermostat` |
| `zones` | the heated space assembled | `ThermalZone` (1R1C or 2R2C) |
| `schedules` | the clock-driven inputs, not physics | `Schedule` (24 or 168 local-hour values), `hot_water_heat` |
| `catalogue` | ready-made homes | `madrid_flat`, `seville_house` |

Two distinctions carry the design. **Metered or free:** every gain heats the
room, but only appliances and machines show on a meter; occupants and sun do
not, and leaving them out makes a fit blame the heating for heat it never
supplied. **Parameter or input:** what the house *is* (conductances,
capacities, machine power, setpoints, base load) are fittable parameters;
what *happens* to it (weather, appliance use, draws, setpoint schedules) are
inputs, from a `Schedule` or from measured data read by `ingest`.

`build_home()` wires a zone, its gains and its machines into one model and
returns a `HomeTwin`. Its `simulate()` fills each input from its schedule,
or from a measured series passed by name, and reports the electricity and
gas meters; `cost_eur()` prices a period. Meter energy is integrated from
the outputs at each step's midpoint state with that step's held inputs,
exactly what the implicit midpoint rule applies, so the whole-home heat
balance closes to rounding.

### The two bundled homes

```bash
python apps/home/examples/example_home.py     # Madrid: gas heating, a January week
python apps/home/examples/seville_summer.py   # Seville: air conditioning, a whole year
```

`madrid_flat()` heats with gas and shows what insulation and a cold spell do:

```
  scenario               electricity kWh   gas kWh
  as built                       94.7       341.4
  insulated envelope             94.7       272.9
  cold spell, -6 °C              94.8       477.2
```

`seville_house()` runs everything on one electricity meter: a reversible
split unit (heat pump in winter, air conditioning in summer) and an electric
*termo*. Over a synthetic year the bill is flat until the air conditioner
becomes the biggest load in the house:

```
  month   outdoor °C   electricity kWh   of it cooling   heating   cost EUR
  Jan         10.7             713             0         207     189.08
  Apr         18.2             488             0           5     132.56
  Jul         28.1             822           331           0     216.35
  Aug         27.5             800           308           0     210.80
  Oct         20.5             516            19           0     139.90

  scenario                 electricity EUR/year
  as built, 25 °C               2050.67
  cooling at 26 °C              1991.00
  August heatwave, +4 °C        2099.22
```

**How the components are tested.** Every expected number comes from the RC
equations, not from a recorded run:

- **The exact discrete solution.** The implicit midpoint rule on a linear
  network is the Padé map, matched to 1e-9 K or better.
- **The continuous solution** (exponential decay, the periodic response to a
  daily outdoor wave, the two modes of a 2R2C zone, the thermostat's ramp and
  approach, saturated cooling), within a bound derived from the step size.
- **Steady states,** started on and held to rounding, heating and cooling.
- **Heat balances** of the zone, the water heater and the whole home, and
  meters that equal the schedule sums exactly.

All of it runs on both backends.

Known limits: an appliance's heat goes either all indoors (the default) or
all outside (`indoors=False`, for a dishwasher or washing machine draining
hot water); a fraction in between needs a heat fraction on the source,
DESIGN.md G2; a heat pump's COP and an air conditioner's EER
are seasonal constants (G4); the thermostat is the cycle-average of an
on/off controller, right for hourly and daily energy but not for
minute-scale cycling; `cost_eur` prices flat tariffs, time-of-use pricing
belongs to the app layer.

## `calibration/`: a month of electricity in, a home you can trust out

`calibrate(twin, HourlyData(start, kwh, outdoor_c))` fits what the
electricity meter can see — how fast the home loses heat, how long it keeps
its warmth, the size of the heating or cooling machine, the always-on load —
and says how far each number can be trusted, in words a householder reads:

```
Calibration: GOOD
Good: over 31 days the twin matches your electricity (a typical hour within 10 % and
the month's total within 0.1 %), and every number below is well determined.

What the month shows about your home:
  • How fast your home loses heat: 179 W for every °C between inside and outside (±1 %).
    On a 5 °C day with 20 °C inside, walls, windows and ventilation together let out
    about 3.1 kW — good.
  • How long your home keeps its warmth: with the heating off it would lose two-thirds
    of its warmth over the outdoor temperature in about 16 hours (±1 %) — good.
  • Size of your heat pump: 4.5 kW of heat at full power (±1 %) — good.
  • Always-on electricity: 146 W (±8 %), about 105 kWh a month whatever you do — good.
```

(`python apps/home/examples/calibrate_month.py`: a synthetic month from a
known flat, the twin starting 50 % off on every value.)

**The verdicts.** *good*: within ±10 %; *usable*: within ±30 %; *not enough
data*: wider, or one of four reasons the month cannot answer, each said in
plain words with what would help:

| Reason | What the householder reads |
| --- | --- |
| heating on gas | the electricity meter does not show how the home gains or loses heat; gas bills or an indoor thermometer would |
| machine never at full power | its size never showed; a colder month, or a morning warm-up after a night setback, would show it |
| indoor temperature never moved | how much heat the home stores never showed; a month with a night setback would |
| the twin cannot reproduce the hours (ASHRAE Guideline 14: hourly CV(RMSE) ≤ 30 %, \|NMBE\| ≤ 10 %) | something big is missing from the twin (an oven, a car charger); add it or measure it with a smart plug |

A record shorter than 28 days, with more than 10 % of hours missing, or
with gaps in the weather is refused before any fitting, saying what to
download instead.

**How it works.** The search is the engine's own `otwin.hybrid.fit_parameters`
(least squares in log-parameters, sensitivities, `otwin.estimate.identifiability`).
What the app adds is the **measurement**: a smart meter records the energy of
each hour, an integral, and `fit_parameters` compares instants (DESIGN.md
G1). `HourlyMeter` presents the home to `fit_parameters` as a model whose
output is the exact hourly mean of the meter, using a vectorised evaluator
of the model's own output expressions (`components.evaluate`, bit-identical
to the backends). Each "±" is the fit's 95 % interval (sandwich form,
robust to noise that grows with consumption) combined with how far the
value would move had the house started the month 3 K warmer or colder,
which nobody measured — the term that keeps a two-node zone's wall storage
honest.

**How it is tested.** Synthetic months from homes with known parameters
(`calibration.synthetic_month`: 5-minute truth, two months of weather
history, a real household's noise), the fit starting 50 % off: noise-free
recovery within 1 %, noisy recovery within the reported ±, and over eight
noise seeds the truth lies inside the reported ± for at least 85 % of values
(in development, 95-100 %). Each "not enough data" case above has its own
test.

**Gas homes.** With the heating on gas, the electricity meter cannot see
the walls; the gas bill can. `HourlyData(..., gas_bills=...)` (or
`HourlyData.from_series(..., gas=...)`) fits each bill's kWh (m³ × Fc × PCS
as printed) together with the hourly electricity, and that measures how fast
the home loses heat, typically to ±20 % from one monthly bill. A bill is a
total over weeks, so the boiler's size and the home's heat storage are
reported as "not measured" without making the whole calibration "not
enough data".

**The interior thermometer.** Every `Thermostat` carries its sensor: a
probe on the side it controls (the room for a heater) that carries no heat.
It gives three outputs: `<machine>.thermostat.temperature` (what it reads),
`.on` (1 while it calls for heat) and `.duty` (the fraction of the time the
machine runs). A householder's thermometer log (`HourlyData(...,
indoor_c=...)`) is fitted hour by hour with the meters, and it shows what no
meter does: how fast the home cools at night (its inertia, the time
constant C / (UA + ventilation)) and how fast the boiler warms it back in
the morning (its size). The thermometer's own offset (where it hangs, its
calibration) is fitted too, so it is not mistaken for the walls. On the gas
sample home, one month with a thermometer gives the inertia to ±2 %; the
whole winter gives heat loss, inertia and boiler size, all "good", on the
truth. Hourly residuals that persist from hour to hour count for their
effective sample size (AR(1)), so the ± does not overstate.

**Radiation to the sky** (ISO 13790 §11.4.6, ISO 52016-1). An envelope that
sees the sky loses, on top of its transmission, Φ_r = R_se · UA · h_r ·
Δθ_er · F_r: R_se 0.04 m²K/W, h_r = 4εσT³ = 4.6 W/m²K, Δθ_er 11 K (the mean
air-to-sky difference), F_r the view factor (roof 1, walls 0.5, ground floor
0). `ThermalZone(sky=...)` puts a `SkyRadiation` step of R_se·h_r·Δθ_er·F_r
kelvin (about 1 K) between the envelope's outer face and the outdoor air,
so the loss is exactly UA × that step and follows UA when a fit changes it.
The survey weighs F_r by where each kind of home loses heat: a flat (not on
the top floor) only through its facades, F_r 0.5; a house through its roof
too, about 0.6. With its larger envelope a 75 m² detached house radiates
about 350 W, the same flat 150 W.

**Example homes follow the answers.** Each example is a hidden real home
(`truth.json`: how it differs from the survey's guess). When the wizard
calibrates it, `survey.example` simulates it again from the answers on the
page, the thermostat by day and at night above all, and rewrites its
electricity, gas bills and thermometer log; the files in `web/samples/` are
the same code run for the example's own answers.

**Several periods.** `HourlyData.join([oct, dec, feb])` makes one record
of separate periods (three monthly downloads with weeks between them). The
twin simulates each period on its own, from its own spin-up, and one set of
parameters is fitted to all of them: it has to match the home in mild and in
cold weather at once. On the gas sample home, three monthly bills from 13,
7 and 10 °C winters narrow the heat loss from ±20 % (any one bill) to ±13 %,
and the one twin reproduces each bill within 0.5 %.

Known limits: the
efficiency (COP, EER) and the thermostat setpoints are taken from the twin,
not fitted; on the NumPy backend a calibration takes about 15 s, on the Rust
engine about 1.5 s.

## `scenarios/`: what if it were colder, the thermostat lower, the walls insulated?

A `ScenarioStudy` holds a calibrated twin, the month it was calibrated on
(its weather and any measured plugs) and the household's `Tariff`. Each
what-if is a small object; running it gives month-by-month kWh, m³ and
euros, as the home is and as it would be, and one sentence comparing them:

```python
study = ScenarioStudy.from_calibration(calibration, data, my_tariff)
study.run(SetpointChange(-1.0)).sentence
```

| Scenario | What changes in the twin |
| --- | --- |
| `OutdoorShift(delta_c)` | every hour of outdoor temperature |
| `SetpointChange(delta_c, machine="heating" \| "cooling" \| name)` | the thermostat: its setpoint parameter, or every hour of its schedule |
| `MoveAppliance(name, from_hours, to_hours)` | an appliance's schedule, moved hour for hour, every day |
| `Insulation(r_value, area_m2, envelope_area_m2)` | the envelope conductance: the board's R (m²·K/W) added in series over the area it covers |
| `TariffChange(tariff)` | nothing physical: the same hours billed differently |

From `python apps/home/examples/what_if.py` (calibrate on January, then ask):

```
• If it were 3 °C colder outside, your home would use 135 kWh more electricity in January 2026,
  and your bills would be €19.51 higher (€155.75 instead of €136.24).
• If you turned the heating down by 1 °C, your home would use 45 kWh less electricity in
  January 2026, and your bills would be €6.75 lower (€129.49 instead of €136.24).
• If you ran the dishwasher at 02:00 instead of 21:00, your home would use the same energy in
  January 2026, but your bills would be €3.36 lower (€132.89 instead of €136.24), because
  electricity is cheaper at those hours.
• If you added insulation of R 2 m²·K/W over 40 m², cutting your home's heat loss from 179 to
  134 W per °C, your home would use 107 kWh less electricity in January 2026, and your bills
  would be €15.98 lower (€120.27 instead of €136.24).
• On the “Tarifa Plana” tariff the same use would cost €13.59 more in January 2026
  (€149.83 instead of €136.24).
```

**Tariffs** follow the Spanish bill: electricity on 2.0TD periods (P1 punta
10-14 and 18-22, P2 llano, P3 valle 00-08 and all weekend and fixed-date
national holidays) or one flat price, plus the power term, meter rental,
the electricity tax (5.11 % of energy and power) and VAT; gas in kWh from
the m³ read (`kWh = m³ × Fc × PCS`), a standing charge, the hydrocarbon tax
and VAT. Months are calendar months in local time, DST days included.

**How it is tested.** On a fixed synthetic twin chosen so every hour is a
closed form (a heat pump under a proportional thermostat that never
saturates, a dishwasher draining outdoors, a gas water heater on the
balcony, a constant 5 °C February), each scenario's month (kWh per tariff
period, gas m³, euros) is checked against the steady-state formulas and
the bill arithmetic written out in the test, to 1e-10 for electricity and
1e-8 for gas (the solver's Newton tolerance), and each sentence word for
word. The same sentences come out of the NumPy and Rust backends and out of
every rerun.

## `web/`: the wizard, a static site

Three steps, entirely client-side: describe the home with selectors only
(`survey` turns the answers into a twin with typical values), drop the
household's exported files (the column mapper reads any other CSV), and
calibrate with one click to get the plain-language report. Files never
leave the browser, and the page says so. It deploys to GitHub Pages
(`.github/workflows/home-pages.yml`, manual) and also opens from disk,
offline. Served, the engine runs in a Web Worker: in Chrome the questions
show in 0.1 s, the engine is ready in 3 s, and the sample month calibrates
in 20 s. See [web/README.md](web/README.md) and the runtime decision in
[web/DECISION.md](web/DECISION.md).

```bash
python apps/home/web/build_bundle.py
python -m http.server -d apps/home/web/dist
```

## Tests

```bash
pytest apps/home                                   # also run by the root `pytest`;
                                                   # components run on Rust too if the engine is installed
python apps/home/tests/fixtures/make_fixtures.py   # regenerate the fixtures
```

The fixtures in `tests/fixtures/data/` are synthetic. Each is generated from a
known truth by `make_fixtures.py`, and the tests check three things for each
one: the committed bytes are what the generator writes, the format is
detected, and parsing returns the truth exactly. `test_ingest_malformed.py`
breaks each fixture the way real files break and checks that the error names
the offending column.

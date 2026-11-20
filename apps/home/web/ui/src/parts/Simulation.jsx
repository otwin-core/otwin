/* "Simulation": the next twelve months of the home, on an average year's
 * weather, from its digital copy; and up to three changes beside it.
 *
 * "As it is today" is the first curve. A scenario is a set of changes made
 * with the same controls as the questions about the home (another heating
 * system, a different temperature, air conditioning, insulation, people,
 * appliances, prices). Each runs on the fitted model and draws its own
 * monthly curve, in euros or kWh, with a yearly total and the difference
 * against today. Months the model never saw are marked as predicted.
 */
import { useEffect, useState } from "react";

import { useT } from "../i18n";
import { Chip } from "./bits";
import { D3Chart, SCENARIO_COLOURS, TWIN_BLUE } from "./charts/D3Chart";
import { Gauge, OptionRow, Segmented, Slider, Switch } from "./controls";

const COLOURS = [TWIN_BLUE, ...SCENARIO_COLOURS]; // the twin is always blue, as in the fit
const MAX_SCENARIOS = 3;
const INSULATION = ["as_is", "walls", "walls_windows"];

export function Simulation({ home, control, questions, onDigitalHome }) {
  const { t, n } = useT();
  const sims = home.simulation || { baseline: null, scenarios: [] };
  const [unit, setUnit] = useState("eur");
  const [running, setRunning] = useState(null); // "baseline" | scenario id
  const [editing, setEditing] = useState(null);
  const byId = Object.fromEntries(questions.map((q) => [q.id, q]));
  const save = (part) => control.setSimulation({ ...sims, ...part });

  useEffect(() => {
    if (sims.baseline || running) return;
    setRunning("baseline");
    control.forecast({}, null).then((r) => {
      save({ baseline: r.ok ? r : null, error: r.ok ? null : r.message });
      setRunning(null);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sims.baseline]);

  const addScenario = () => {
    const id = `s${Date.now().toString(36)}`;
    const sc = { id, name: t("sim_scenario_n", { n: sims.scenarios.length + 1 }), changes: {}, prices: null, result: null };
    save({ scenarios: [...sims.scenarios, sc] });
    setEditing(id);
  };
  const update = (id, part) => save({ scenarios: sims.scenarios.map((s) => (s.id === id ? { ...s, ...part } : s)) });
  const remove = (id) => save({ scenarios: sims.scenarios.filter((s) => s.id !== id) });
  const run = async (sc) => {
    setRunning(sc.id);
    const r = await control.forecast(sc.changes, sc.prices);
    update(sc.id, { result: r.ok ? r : null, error: r.ok ? null : r.message });
    setRunning(null);
  };

  const curves = [
    sims.baseline ? { id: "base", name: t("sim_today"), result: sims.baseline, colour: COLOURS[0] } : null,
    ...sims.scenarios.map((s, i) => (s.result ? { id: s.id, name: s.name, result: s.result, colour: COLOURS[i + 1] } : null)),
  ].filter(Boolean);

  return (
    <div className="sim">
      <h1>{t("page_simulation")}</h1>
      <p className="lead">{t("sim_lead2")}</p>
      {sims.error ? <p className="error">{sims.error}</p> : null}

      <div className="sim-tools">
        <Segmented
          name="unit"
          options={[
            { value: "eur", label: t("sim_unit_eur") },
            { value: "kwh", label: t("sim_unit_kwh") },
          ]}
          value={unit}
          onChange={setUnit}
        />
        <button type="button" id="add-scenario" className="primary" disabled={sims.scenarios.length >= MAX_SCENARIOS} onClick={addScenario}>
          {t("sim_add")}
        </button>
        <span className="small">{t("sim_max", { n: MAX_SCENARIOS })}</span>
      </div>

      {running === "baseline" ? <p className="status"><span className="bar"><i /></span><span>{t("sim_running_base")}</span></p> : null}
      {curves.length ? <Chart curves={curves} unit={unit} /> : null}
      {curves.length ? <Totals curves={curves} unit={unit} /> : null}

      <ol className="scenarios">
        {sims.scenarios.map((sc, i) => (
          <li key={sc.id} className="scenario" data-scenario={sc.id} style={{ borderLeftColor: COLOURS[i + 1] }}>
            <div className="scenario-head">
              <input type="text" className="scenario-name" value={sc.name} onChange={(e) => update(sc.id, { name: e.target.value })} aria-label={t("sim_name")} />
              <span className="small scenario-desc">{describe(sc.changes, sc.prices, byId, t, n)}</span>
              <span style={{ display: "flex", gap: 8 }}>
                <button type="button" className="small" data-edit={sc.id} onClick={() => setEditing(editing === sc.id ? null : sc.id)}>
                  {editing === sc.id ? t("close") : t("sim_edit")}
                </button>
                <button type="button" className="small primary" data-run={sc.id} disabled={!!running} onClick={() => run(sc)}>
                  {running === sc.id ? t("sim_running") : sc.result ? t("sim_run_again") : t("sim_run")}
                </button>
                <button type="button" className="remove" aria-label={t("remove")} onClick={() => remove(sc.id)}>
                  ×
                </button>
              </span>
            </div>
            {sc.error ? <p className="error">{sc.error}</p> : null}
            {editing === sc.id ? <Editor scenario={sc} home={home} byId={byId} onChange={(changes, prices) => update(sc.id, { changes, prices, result: null })} /> : null}
          </li>
        ))}
      </ol>
      <p>
        <button type="button" className="plain" onClick={onDigitalHome}>
          ← {t("page_calibration")}
        </button>
      </p>
    </div>
  );
}

/* What a scenario changes, in a few words. */
function describe(changes, prices, byId, t, n) {
  const parts = [];
  for (const [k, v] of Object.entries(changes)) {
    if (k === "insulation") {
      if (v !== "as_is") parts.push(t(`sim_ins_${v}`));
      continue;
    }
    const q = byId[k];
    if (!q) continue;
    if (q.kind === "switch") {
      parts.push(t(`sim_${k}_${v}`));
      continue;
    }
    const opt = q.options?.find((o) => o.value === v);
    parts.push(opt ? opt.label : k === "thermostat" || k === "cooling_setpoint" ? `${v} °C` : `${v}${q.unit ? ` ${q.unit}` : ""}`);
  }
  if (prices) parts.push(t("sim_prices_short", { e: n(prices.electricity, 2), g: n(prices.gas, 3) }));
  return parts.length ? parts.join(" · ") : t("sim_no_changes");
}

/* The controls of a scenario: the same as the questions about the home. */
function Editor({ scenario, home, byId, onChange }) {
  const { t } = useT();
  const base = home.answers || {};
  const changes = scenario.changes;
  const value = (id) => (id in changes ? changes[id] : base[id]);
  const set = (id, v) => {
    const next = { ...changes };
    if (String(v) === String(base[id])) delete next[id];
    else next[id] = v;
    onChange(next, scenario.prices);
  };
  const num = (id, fallback) => {
    const v = value(id);
    const legacy = { s: 50, m: 75, l: 105, xl: 140, pre1980: 1965, "1980_2006": 1995, post2007: 2015, auto: 0 };
    return v in legacy ? legacy[v] : Number(v ?? fallback);
  };
  const q = (id) => byId[id] || { options: [], minimum: 0, maximum: 1, step: 1 };
  const prices = scenario.prices || { electricity: home.report?.money?.electricity_price || 0.17, gas: home.report?.money?.gas_price || 0.075 };
  const setPrice = (k, v) => onChange(changes, { ...prices, [k]: v });
  const Row = ({ id, children }) => (
    <div className="sim-row" data-control={id}>
      <span className="sim-label">{q(id).label || t(`sim_${id}`)}</span>
      {children}
    </div>
  );
  return (
    <div className="sim-editor">
      <Row id="heating">
        <OptionRow name="heating" options={q("heating").options} value={value("heating")} onChange={(v) => set("heating", v)} />
      </Row>
      {value("heating") !== "none" ? (
        <Row id="heating_power">
          <Slider name="heating_power" value={num("heating_power", 0)} min={0} max={40} step={1} unit="kW" zeroLabel={q("heating_power").options?.[0]?.label} onChange={(v) => set("heating_power", String(v))} />
        </Row>
      ) : null}
      {value("heating") !== "none" ? (
        <Row id="thermostat">
          <Gauge name="thermostat" value={num("thermostat", 20)} min={16} max={26} step={0.5} onChange={(v) => set("thermostat", String(v))} />
        </Row>
      ) : null}
      <Row id="night">
        <Switch name="night" checked={value("night") === "lower"} label={q("night").options?.find((o) => o.value === value("night"))?.label} onChange={(on) => set("night", on ? "lower" : "same")} />
      </Row>
      <Row id="cooling">
        <Switch name="cooling" checked={value("cooling") === "yes"} label={q("cooling").options?.find((o) => o.value === value("cooling"))?.label} onChange={(on) => set("cooling", on ? "yes" : "no")} />
      </Row>
      {value("cooling") === "yes" ? (
        <Row id="cooling_setpoint">
          <Gauge name="cooling_setpoint" value={num("cooling_setpoint", 25)} min={22} max={28} step={0.5} onChange={(v) => set("cooling_setpoint", String(v))} />
        </Row>
      ) : null}
      <div className="sim-row" data-control="insulation">
        <span className="sim-label">{t("sim_insulation")}</span>
        <Segmented name="insulation" options={INSULATION.map((v) => ({ value: v, label: t(`sim_ins_${v}`) }))} value={changes.insulation || "as_is"} onChange={(v) => set("insulation", v)} />
      </div>
      <Row id="water">
        <OptionRow name="water" options={q("water").options} value={value("water")} onChange={(v) => set("water", v)} />
      </Row>
      <Row id="people">
        <Slider name="people" value={num("people", 2)} min={1} max={6} step={1} onChange={(v) => set("people", String(v))} />
      </Row>
      <Row id="appliances">
        <div className="switches">
          {q("appliances").options.map((o) => {
            const on = (value("appliances") || []).includes(o.value);
            return <Switch key={o.value} name={`appliances.${o.value}`} checked={on} label={o.label} onChange={(next) => set("appliances", next ? [...(value("appliances") || []), o.value] : (value("appliances") || []).filter((v) => v !== o.value))} />;
          })}
        </div>
      </Row>
      <div className="sim-row" data-control="prices">
        <span className="sim-label">{t("sim_prices")}</span>
        <div className="prices">
          <Slider name="price_electricity" value={prices.electricity} min={0.08} max={0.4} step={0.01} format={(v) => `${v.toFixed(2)} €/kWh ${t("card_electricity").toLowerCase()}`} onChange={(v) => setPrice("electricity", v)} />
          <Slider name="price_gas" value={prices.gas} min={0.03} max={0.15} step={0.005} format={(v) => `${v.toFixed(3)} €/kWh ${t("card_gas").toLowerCase()}`} onChange={(v) => setPrice("gas", v)} />
        </div>
      </div>
    </div>
  );
}

function Chart({ curves, unit }) {
  const { t } = useT();
  const year = curves[0].result.year || 2026;
  const at = (m) => new Date(year, m.month - 1, 15, 12);
  const val = (m) => (unit === "eur" ? m.eur : m.electricity_kwh + m.gas_kwh);
  const band = (m) => (unit === "eur" ? m.band_eur : m.band_kwh);
  const series = curves.map((c, i) => ({
    id: c.id,
    name: c.name,
    colour: c.colour,
    kind: "line",
    primary: i === 0,
    points: c.result.months.map((m) => ({ x: at(m), y: val(m) })),
    band: c.result.months[0].band_eur ? c.result.months.map((m) => ({ x: at(m), lo: band(m)[0], hi: band(m)[1] })) : null,
  }));
  const unseen = curves[0].result.months.filter((m) => !m.seen).map((m) => m.label);
  return (
    <div className="sim-chart">
      <D3Chart series={series} unit={unit === "eur" ? "€" : "kWh"} yLabel={unit === "eur" ? t("sim_unit_eur_month") : t("sim_unit_kwh_month")} height={340} monthly bandLabel={t("band_label")} caption={unseen.length ? t("sim_predicted_months", { months: unseen.join(", ") }) : ""} />
    </div>
  );
}

function Totals({ curves, unit }) {
  const { t, n } = useT();
  const base = curves[0].result.totals;
  const val = (tot) => (unit === "eur" ? tot.eur : tot.electricity_kwh + tot.gas_kwh);
  const fmt = (v) => (unit === "eur" ? t("eur", { eur: n(v) }) : t("kwh", { kwh: n(v) }));
  return (
    <table className="data sim-totals">
      <thead>
        <tr>
          <th>{t("sim_curve")}</th>
          <th>{t("card_electricity")}</th>
          <th>{t("card_gas")}</th>
          <th>{t("sim_year")}</th>
          <th>{t("sim_vs_today")}</th>
        </tr>
      </thead>
      <tbody>
        {curves.map((c) => {
          const tot = c.result.totals;
          const d = val(tot) - val(base);
          return (
            <tr key={c.id}>
              <td>
                <i className="dot" style={{ background: c.colour }} /> {c.name}
                {c.result.heater !== curves[0].result.heater ? <Chip>{t(`machine_${c.result.heater}`)}</Chip> : null}
              </td>
              <td>{unit === "eur" ? fmt(tot.eur_electricity) : fmt(tot.electricity_kwh)}</td>
              <td>{unit === "eur" ? fmt(tot.eur_gas) : fmt(tot.gas_kwh)}</td>
              <td>
                <strong>{fmt(val(tot))}</strong>
              </td>
              <td className={d < 0 ? "saves" : d > 0 ? "costs" : ""}>{c.id === "base" ? "—" : `${d > 0 ? "+" : ""}${fmt(d)}`}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

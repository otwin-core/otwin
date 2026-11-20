/* The areas of a fit, each a panel: where the money goes, the heating,
 * the improvements, and month by month. The pages place them.
 */
import { useT } from "../i18n";
import { Chip } from "./bits";
import { DailyChart, IndoorChart } from "./Charts";

function Empty() {
  const { t } = useT();
  return <p className="small">{t("explore_empty")}</p>;
}

function Bars({ rows }) {
  const { t, n } = useT();
  const max = Math.max(...rows.map((r) => r.eur), 1);
  return (
    <ul className="bars">
      {rows.map((r) => (
        <li key={`${r.use}-${r.fuel}`}>
          <span className="bar-label">
            {r.label} ({t(`fuel_${r.fuel}`)})
          </span>
          <span className="bar">
            <i className={r.fuel} style={{ width: `${(100 * r.eur) / max}%` }} />
          </span>
          <span className="bar-value">
            {t("eur", { eur: n(r.eur) })} · {t("kwh", { kwh: n(r.kwh) })}
          </span>
        </li>
      ))}
    </ul>
  );
}

export function Money({ report, estimate }) {
  const { t, n } = useT();
  if (!report) {
    if (!estimate) return <Empty />;
    return (
      <>
        <p className="small">
          {t("estimate_badge")}:{" "}
          {t("estimate_text", {
            province: estimate.province,
            temp: n(estimate.january_c, 1),
            eur: n(estimate.eur),
            pct: n(100 * estimate.heating_share),
          })}
        </p>
        <Bars rows={estimate.by_use} />
      </>
    );
  }
  const m = report.money;
  const hasGas = m.by_use.some((r) => r.fuel === "gas");
  return (
    <>
      <p className="small">
        {hasGas
          ? t("money_intro", {
              days: n(m.days),
              gas: t("money_per_kwh", { eur: n(m.gas_price, 3) }),
              bills: m.from_bills ? t("money_from_bills") : "",
            })
          : t("money_intro_elec", { days: n(m.days) })}
      </p>
      <Bars rows={m.by_use} />
      {report.gas ? <Lines title={t("card_gas")} lines={report.gas.sentences} /> : null}
      {report.water ? <Lines title={t("card_water")} lines={report.water.sentences} /> : null}
    </>
  );
}

function Lines({ title, lines }) {
  if (!lines?.length) return null;
  return (
    <section style={{ borderTop: "1px solid #111", paddingTop: 12, marginTop: 18 }}>
      <p className="tile-label">{title}</p>
      {lines.map((line) => (
        <p key={line}>{line}</p>
      ))}
    </section>
  );
}

export function Heating({ report }) {
  const { t, n } = useT();
  if (!report) return <Empty />;
  const facts = [
    report.keeps_warm_hours != null && report.keeps_warm_verdict !== "not enough data"
      ? t("keeps_warm", { h: n(report.keeps_warm_hours) })
      : t("keeps_warm_unknown"),
    report.boiler === "measured"
      ? t("boiler_measured", { kw: n(report.boiler_kw, 1) })
      : report.boiler === "given"
        ? t("boiler_given", { kw: n(report.boiler_kw, 1) })
        : report.boiler === "bigger_than_needed"
        ? t("boiler_bigger")
        : t("boiler_unknown"),
    report.running != null ? t("running", { pct: n(100 * report.running) }) : null,
  ].filter(Boolean);
  return (
    <>
      <ul className="facts">
        {facts.map((f) => (
          <li key={f}>{f}</li>
        ))}
      </ul>
      {report.heating.map((line) => (
        <p key={line}>{line}</p>
      ))}
      {report.periods
        .filter((p) => p.indoor)
        .map((p) => (
          <IndoorChart
            key={p.label}
            points={p.indoor}
            title={
              report.periods.length > 1
                ? t("indoor_week_of", { label: p.label })
                : t("indoor_week")
            }
          />
        ))}
      <HowWeKnow report={report} />
    </>
  );
}

export function HowWeKnow({ report }) {
  const { t } = useT();
  if (!report) return null;
  return (
    <details className="how">
      <summary>{t("how_we_know")}</summary>
      <ul className="findings">
        {report.findings.map((f) => (
          <li className="finding" key={f.key}>
            <div className="finding-head">
              <span className="finding-label">{f.label}</span>
              <Chip kind={f.verdict === "good" ? "on" : f.verdict === "usable" ? "warn" : "bad"}>
                {t(`verdict_${f.verdict}`)}
              </Chip>
            </div>
            <p>{f.text}</p>
            {f.reason ? <p className="reason">{f.reason}</p> : null}
          </li>
        ))}
      </ul>
    </details>
  );
}

export function WhatIf({ report }) {
  const { t } = useT();
  if (!report?.whatif?.length) return <Empty />;
  return (
    <>
      <p className="small">{t("whatif_intro")}</p>
      <div className="whatifs">
        {report.whatif.map((w) => (
          <div
            key={w.key}
            data-whatif={w.key}
            className={`whatif ${w.eur_month_change < -0.5 ? "saves" : w.eur_month_change > 0.5 ? "costs" : ""}`}
          >
            <p className="title">{w.title}</p>
            <p className="effect">{w.effect}</p>
          </div>
        ))}
      </div>
      <p className="small">{report.whatif_basis}</p>
    </>
  );
}

export function Months({ report }) {
  const { t, n } = useT();
  if (!report) return <Empty />;
  const cell = (v) => (v == null ? "—" : n(v));
  return (
    <>
      <table className="data">
        <thead>
          <tr>
            {["months_period", "months_outdoor", "months_elec", "months_elec_model", "months_gas", "months_gas_model"].map(
              (h) => (
                <th key={h}>{t(h)}</th>
              ),
            )}
          </tr>
        </thead>
        <tbody>
          {report.periods.map((p) => (
            <tr key={p.label}>
              <td>{p.label}</td>
              <td>{`${n(p.mean_c)} °C`}</td>
              <td>{cell(p.electricity_kwh)}</td>
              <td>{cell(p.twin_electricity_kwh)}</td>
              <td>{cell(p.gas_bill_kwh)}</td>
              <td>{cell(p.twin_gas_kwh)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {report.periods.map((p) => (
        <DailyChart key={p.label} daily={p.daily} title={t("elec_per_day", { label: p.label })} />
      ))}
    </>
  );
}

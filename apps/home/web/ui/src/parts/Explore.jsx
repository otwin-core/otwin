/* The five areas: where the money goes, the heating, what if, can I trust
 * it, and month by month. Radix Tabs underneath; the look is ours.
 */
import * as Tabs from "@radix-ui/react-tabs";

import { useT } from "../i18n";
import { Chip } from "./bits";
import { DailyChart, IndoorChart } from "./Charts";

const AREAS = ["money", "heating", "whatif", "trust", "months"];

export function Explore({ report, estimate, periods, trustBusy, onRunTrust }) {
  const { t } = useT();
  return (
    <Tabs.Root defaultValue="money">
      <Tabs.List className="explore-tabs" aria-label={t("explore_title")}>
        {AREAS.map((a) => (
          <Tabs.Trigger key={a} value={a} data-tab={a}>
            {t(`tab_${a}`)}
          </Tabs.Trigger>
        ))}
      </Tabs.List>
      <Tabs.Content className="panel" value="money">
        <Money report={report} estimate={estimate} />
      </Tabs.Content>
      <Tabs.Content className="panel" value="heating">
        <Heating report={report} />
      </Tabs.Content>
      <Tabs.Content className="panel" value="whatif">
        <WhatIf report={report} />
      </Tabs.Content>
      <Tabs.Content className="panel" value="trust">
        <Trust report={report} periods={periods} busy={trustBusy} onRun={onRunTrust} />
      </Tabs.Content>
      <Tabs.Content className="panel" value="months">
        <Months report={report} />
      </Tabs.Content>
    </Tabs.Root>
  );
}

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

function Money({ report, estimate }) {
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

function Heating({ report }) {
  const { t, n } = useT();
  if (!report) return <Empty />;
  const facts = [
    report.keeps_warm_hours != null && report.keeps_warm_verdict !== "not enough data"
      ? t("keeps_warm", { h: n(report.keeps_warm_hours) })
      : t("keeps_warm_unknown"),
    report.boiler === "measured"
      ? t("boiler_measured", { kw: n(report.boiler_kw, 1) })
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

function HowWeKnow({ report }) {
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

function WhatIf({ report }) {
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

function Trust({ report, periods, busy, onRun }) {
  const { t } = useT();
  if (!report) return <Empty />;
  const trust = report.trust;
  return (
    <>
      <p>{report.confidence_text}</p>
      <p className="small">{t("trust_intro")}</p>
      {trust?.sentences ? (
        <div
          className={`trust ${trust.passed ? "passed" : trust.status === "done" ? "failed" : ""}`}
        >
          {trust.sentences.map((s) => (
            <p key={s}>{s}</p>
          ))}
        </div>
      ) : (periods?.length || 0) < 2 ? (
        <p className="small">{t("trust_needs_two")}</p>
      ) : (
        <p>
          <button type="button" className="primary" id="run-trust" disabled={busy} onClick={onRun}>
            {t("trust_run")}
          </button>
        </p>
      )}
      <HowWeKnow report={report} />
    </>
  );
}

function Months({ report }) {
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

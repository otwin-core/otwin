/* The pieces a home is shown with. "My home" and "Demo" both use them:
 *   HomeHead  the name, its line, the tools and Edit
 *   Answer    the traffic light, the money, how sure we are, the house drawn
 * The areas (Explore.jsx) are placed by the pages themselves.
 */
import { useT } from "../i18n";
import { bandOf, Block, ConfBar, Lights, Status } from "./bits";
import { House } from "./House";

const LEVEL = { reliable: 3, approximate: 2, more_data: 1 };

export function HomeHead({ title, subtitle, tools, onEdit }) {
  const { t } = useT();
  return (
    <div className="home-head">
      <div>
        <h1>{title}</h1>
        <p className="muted">{subtitle}</p>
        {tools}
      </div>
      <button type="button" className="edit" id="edit" onClick={onEdit}>
        {t("edit")}
      </button>
    </div>
  );
}

/* `exact`: the cost is what the bills say (a demo); otherwise it is marked
   as an approximation. */
export function Answer({ slice, control, exact }) {
  const { t, n } = useT();
  const { home, cards, report, previous } = slice;
  const estimate = home?.ok ? home.estimate : null;
  const working = control.task === "analyse" || control.task === "preparing";
  const band = report ? bandOf(report.letter) : estimate ? bandOf(home.typical_letter) : null;
  const flows = report ? report.flows : estimate ? estimate.flows : null;
  const caption = report
    ? t("house_caption_report", { days: n(report.money.days) })
    : estimate
      ? t("house_caption_estimate", { province: estimate.province, temp: n(estimate.january_c, 1) })
      : "";
  const bill = flows?.bill || null;
  const cost = report
    ? { eur: report.money.eur_per_month, approx: !(exact || report.money.from_bills) }
    : estimate
      ? { eur: estimate.eur, approx: true }
      : null;
  const condShare = flows
    ? Math.round(
        (100 * (flows.conditioning || []).reduce((a, c) => a + c.eur, 0)) /
          Math.max((flows.by_use || []).reduce((a, r) => a + r.eur, 0), 1),
      )
    : null;
  return (
    <Block colour="red">
      <div className={`answer ${working ? "updating" : ""}`} aria-live="polite">
        <div className="answer-grid" style={{ borderTop: 0 }}>
          <div className="tile">
            <p className="tile-label">{t("keeps_heat")}</p>
            <Lights band={band} />
            <p className="keeps">{band ? t(`keeps_${band}`) : "–"}</p>
            <p className="small" style={{ marginTop: 8 }}>
              {report
                ? t("typical_keeps", { band: t(`keeps_${bandOf(report.typical_letter)}`).toLowerCase() })
                : t("estimate_badge")}
            </p>
          </div>
          <div className="tile">
            <p className="tile-label">{t("per_month")}</p>
            <div className="money">
              {cost ? t("eur", { eur: n(cost.eur) }) : "–"}
              {cost?.approx ? <span className="approx"> {t("cost_approx")}</span> : null}
            </div>
            <p className="small" style={{ marginTop: 8 }}>
              {bill
                ? bill.gas
                  ? t("split_fuels", { e: n(bill.electricity.eur), g: n(bill.gas.eur) })
                  : t("split_electricity", { e: n(bill.electricity.eur) })
                : ""}
              {condShare != null ? ` · ${t("conditioning_share", { pct: condShare })}` : ""}
            </p>
            <p className="small">
              {report ? t("per_month_note", { eur: n(report.money.eur), days: n(report.money.days) }) : estimate ? t("estimate_badge") : ""}
            </p>
          </div>
          <div className="tile">
            <p className="tile-label">{t("confidence")}</p>
            <ConfBar level={report ? LEVEL[report.confidence] : 0} />
            <p className="small">{report ? t(`conf_${report.confidence}`) : t("conf_estimate")}</p>
          </div>
        </div>
        {flows ? (
          <div className="answer-house">
            <House flows={flows} band={band} caption={caption} />
          </div>
        ) : null}
        <div style={{ padding: "16px 20px 0" }}>
          <p className="answer-text">
            {report
              ? report.confidence_text
              : control.failure && cards?.ready
                ? t("analysis_failed", { message: control.failure })
                : estimate
                  ? t("estimate_text", {
                      province: estimate.province,
                      temp: n(estimate.january_c, 1),
                      eur: n(estimate.eur),
                      pct: n(100 * estimate.heating_share),
                    })
                  : ""}
          </p>
          {working ? (
            <Status text={control.task === "preparing" ? t("preparing") : t("updating_long", { s: control.seconds })} />
          ) : null}
          <Changed previous={previous} report={report} />
          <p className="small">{t("lights_note")}</p>
        </div>
      </div>
    </Block>
  );
}

function Changed({ previous, report }) {
  const { t, n } = useT();
  if (!previous || !report) return null;
  const parts = [];
  if (bandOf(previous.letter) !== bandOf(report.letter)) {
    parts.push(
      t("changed_keeps", {
        a: t(`keeps_${bandOf(previous.letter)}`).toLowerCase(),
        b: t(`keeps_${bandOf(report.letter)}`).toLowerCase(),
      }),
    );
  }
  if (Math.round(previous.money.eur_per_month) !== Math.round(report.money.eur_per_month)) {
    parts.push(t("changed_eur", { a: n(previous.money.eur_per_month), b: n(report.money.eur_per_month) }));
  }
  if (previous.confidence !== report.confidence) {
    parts.push(t("changed_conf", { a: t(`conf_${previous.confidence}`), b: t(`conf_${report.confidence}`) }));
  }
  return <p className="changed">{t("changed", { what: parts.join("; ") || t("changed_nothing") })}</p>;
}

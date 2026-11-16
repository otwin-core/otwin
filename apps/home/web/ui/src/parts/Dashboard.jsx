/* One home on one screen: the answer, the next best step, the data and the
 * five areas. "Your home" and "Demo" both use it; only the title, the banner
 * and what Edit means differ.
 */
import { useT } from "../i18n";
import { Block, ConfBar, Letter, Status } from "./bits";
import { DataCards } from "./Cards";
import { Explore } from "./Explore";

const LEVEL = { reliable: 3, approximate: 2, more_data: 1 };

export function Dashboard({ title, banner, slice, control, province, onEdit, onPick, fileInput }) {
  const { t, n } = useT();
  const { home, cards, report, previous } = slice;
  const estimate = home?.ok ? home.estimate : null;
  const working = control.task === "analyse" || control.task === "trust" || control.task === "preparing";
  return (
    <div>
      {banner}
      <div className="home-head" style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div>
          <h1>{title}</h1>
          <p className="muted">{home?.ok ? home.header : ""}</p>
        </div>
        <button type="button" onClick={onEdit}>
          {t("edit")}
        </button>
      </div>

      <Block colour="red">
        <div className={`answer ${working ? "updating" : ""}`} aria-live="polite">
          <div className="answer-grid" style={{ borderTop: 0 }}>
            <div className="tile">
              <p className="tile-label">{t("keeps_heat")}</p>
              <Letter letter={report ? report.letter : estimate ? home.typical_letter : "–"} />
              <p className="small" style={{ marginTop: 8 }}>
                {report ? t("typical_letter", { letter: report.typical_letter }) : t("estimate_badge")}
              </p>
            </div>
            <div className="tile">
              <p className="tile-label">{t("per_month")}</p>
              <div className="money">
                {report
                  ? t("eur", { eur: n(report.money.eur_per_month) })
                  : estimate
                    ? t("eur", { eur: n(estimate.eur) })
                    : "–"}
              </div>
              <p className="small" style={{ marginTop: 8 }}>
                {report
                  ? `${t("per_month_note", { eur: n(report.money.eur), days: n(report.money.days) })} · ${t("heating_share", { pct: n(100 * report.heating_share) })}`
                  : estimate
                    ? `${t("estimate_badge")} · ${t("heating_share", { pct: n(100 * estimate.heating_share) })}`
                    : ""}
              </p>
            </div>
            <div className="tile">
              <p className="tile-label">{t("confidence")}</p>
              <ConfBar level={report ? LEVEL[report.confidence] : 0} />
              <p className="small">{report ? t(`conf_${report.confidence}`) : t("conf_estimate")}</p>
            </div>
          </div>
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
              <Status
                text={
                  control.task === "preparing"
                    ? t("preparing")
                    : control.task === "trust"
                      ? t("trust_running", { s: control.seconds })
                      : t("updating_long", { s: control.seconds })
                }
              />
            ) : null}
            <Changed previous={previous} report={report} />
            <p className="small">{t("not_official")}</p>
          </div>
        </div>
      </Block>

      {cards?.next ? (
        <div className="banner next">
          <div>
            <p className="title">{t("next_title")}</p>
            <p style={{ margin: 0 }}>{t(`next_${cards.next}`)}</p>
          </div>
          <NextAction next={cards.next} cards={cards} control={control} onPick={onPick} />
        </div>
      ) : null}

      <h2>{t("data_title")}</h2>
      <p className="small">{t("drop_hint")}</p>
      {fileInput}
      <DataCards
        cards={cards}
        summaries={control.summaries}
        province={province}
        onPick={onPick}
        onRemove={control.removeFile}
        onMap={control.mapFile}
        onBill={control.addBill}
        weather={{
          busy: control.weatherBusy,
          message: control.weatherMessage,
          fetch: control.fetchWeather,
        }}
      />

      <h2 style={{ marginTop: 36 }}>{t("explore_title")}</h2>
      <Explore
        report={report}
        estimate={estimate}
        periods={cards?.periods}
        trustBusy={control.task === "trust"}
        onRunTrust={control.runTrust}
      />
    </div>
  );
}

function NextAction({ next, cards, control, onPick }) {
  const { t } = useT();
  if (next === "allow_weather") {
    const card = cards.cards.find((c) => c.kind === "weather");
    return (
      <button
        type="button"
        className="primary"
        disabled={control.weatherBusy}
        onClick={() => control.fetchWeather(card.request)}
      >
        {t("act_weather")}
      </button>
    );
  }
  if (next === "explore") {
    return (
      <button
        type="button"
        onClick={() => document.querySelector('[data-tab="whatif"]')?.click()}
      >
        {t("act_explore")}
      </button>
    );
  }
  return (
    <button type="button" className="primary" onClick={onPick}>
      {t("act_add")}
    </button>
  );
}

function Changed({ previous, report }) {
  const { t, n } = useT();
  if (!previous || !report) return null;
  const parts = [];
  if (previous.letter !== report.letter) {
    parts.push(t("changed_letter", { a: previous.letter, b: report.letter }));
  }
  if (Math.round(previous.money.eur_per_month) !== Math.round(report.money.eur_per_month)) {
    parts.push(
      t("changed_eur", {
        a: n(previous.money.eur_per_month),
        b: n(report.money.eur_per_month),
      }),
    );
  }
  if (previous.confidence !== report.confidence) {
    parts.push(
      t("changed_conf", {
        a: t(`conf_${previous.confidence}`),
        b: t(`conf_${report.confidence}`),
      }),
    );
  }
  return <p className="changed">{t("changed", { what: parts.join("; ") || t("changed_nothing") })}</p>;
}

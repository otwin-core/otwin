/* The questions about a home: three short screens, then "this is your home".
 *
 * The same screens describe the householder's own home and, in the Demo
 * section, the demo home (whose records are simulated again from them).
 */
import { useEffect, useState } from "react";

import { useT } from "../i18n";
import { Block, Letter, Question } from "./bits";

const PAGES = [
  ["ob_where", ["province", "home_type", "size", "built"]],
  ["ob_heat", ["heating", "water", "cooking", "cooling"]],
  ["ob_live", ["thermostat", "night", "people", "appliances"]],
];

export function defaultAnswers(questions) {
  const out = {};
  for (const q of questions) out[q.id] = Array.isArray(q.default) ? [...q.default] : q.default;
  return out;
}

export function Onboarding({ questions, answers, onSave, onCancel, fetchHome, saveLabel, lead }) {
  const { t, n } = useT();
  const [page, setPage] = useState(0);
  const [draft, setDraft] = useState(() => answers || defaultAnswers(questions));
  const [home, setHome] = useState(null);
  const byId = Object.fromEntries(questions.map((q) => [q.id, q]));
  const last = page === PAGES.length;

  useEffect(() => {
    if (!last) return undefined;
    let gone = false;
    setHome(null);
    fetchHome(draft).then((out) => !gone && setHome(out));
    return () => {
      gone = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [last, page]);

  const set = (id, value) => setDraft((d) => ({ ...d, [id]: value }));

  return (
    <div>
      {last ? null : <p className="stepcount">{t("step_of", { n: page + 1, total: PAGES.length })}</p>}
      <h1>{t(last ? "ob_summary" : PAGES[page][0])}</h1>
      {lead && page === 0 ? <p className="lead">{lead}</p> : null}
      {last ? (
        <Summary home={home} t={t} n={n} />
      ) : (
        <form onSubmit={(e) => e.preventDefault()}>
          {PAGES[page][1].map((id) => (
            <Question key={id} question={byId[id]} value={draft[id]} onChange={(v) => set(id, v)} />
          ))}
        </form>
      )}
      <div className="actions">
        <button
          type="button"
          onClick={() => (page === 0 ? onCancel && onCancel() : setPage(page - 1))}
          hidden={page === 0 && !onCancel}
        >
          {page === 0 ? t("cancel") : t("back")}
        </button>
        <button
          type="button"
          className="primary"
          onClick={() => (last ? onSave(draft) : setPage(page + 1))}
        >
          {last ? saveLabel || t("go_home") : t("next")}
        </button>
      </div>
    </div>
  );
}

function Summary({ home, t, n }) {
  if (!home) return <p className="small">{t("preparing")}</p>;
  if (!home.ok) return <p className="error">{home.message}</p>;
  const e = home.estimate;
  return (
    <>
      <Block>
        <dl className="summary">
          {home.summary.map((row) => (
            <div key={row.topic} style={{ display: "contents" }}>
              <dt>{row.topic}</dt>
              <dd>{row.text}</dd>
            </div>
          ))}
        </dl>
      </Block>
      <Block colour="yellow">
        <p className="tile-label">{t("estimate_title")}</p>
        <div className="estimate-row">
          <Letter letter={home.typical_letter} small />
          <p style={{ margin: 0 }}>
            {t("estimate_text", {
              province: e.province,
              temp: n(e.january_c, 1),
              eur: n(e.eur),
              pct: n(100 * e.heating_share),
            })}
          </p>
        </div>
        <p className="small" style={{ marginTop: 10 }}>
          {t("typical_letter", { letter: home.typical_letter })}. {t("estimate_note")}
        </p>
      </Block>
    </>
  );
}

/* "Demo": homes whose answer we already know, with their own data.
 *
 * Everything demo lives here: the picker, the demo's own settings and its
 * results. The householder's own home is never touched from this section.
 */
import { useState } from "react";

import { useT } from "../i18n";
import { Dashboard } from "./Dashboard";
import { Onboarding } from "./Onboarding";

export const DEMOS = ["gas_winter", "gas_dec_jan", "electric"];

export function Demo({ slice, control, questions, province, onPick, fileInput, onChoose, onLeave }) {
  const { t } = useT();
  const [editing, setEditing] = useState(false);

  if (!slice.key) {
    return (
      <div>
        <h1>{t("demo_title")}</h1>
        <p className="lead">{t("demo_lead")}</p>
        <h2>{t("demo_pick")}</h2>
        <div className="demos">
          {DEMOS.map((key) => (
            <button key={key} type="button" className="demo-card" data-example={key} onClick={() => onChoose(key)}>
              <span className="band" />
              <span className="inner">
                <span className="name">{t(`demo_${key}`)}</span>
                <span className="small">{t(`demo_${key}_desc`)}</span>
              </span>
            </button>
          ))}
        </div>
      </div>
    );
  }

  if (editing) {
    return (
      <Onboarding
        questions={questions}
        answers={slice.answers}
        fetchHome={control.fetchHome}
        lead={t("demo_edit_lead")}
        saveLabel={t("save_changes")}
        onCancel={() => setEditing(false)}
        onSave={async (answers) => {
          setEditing(false);
          await control.setAnswers(answers);
        }}
      />
    );
  }

  return (
    <Dashboard
      title={`${t("demo_home_title")}: ${t(`demo_${slice.key}`)}`}
      banner={
        <div className="banner demo">
          <span>{t("demo_not_yours")}</span>
          <span style={{ display: "flex", gap: 8 }}>
            <button type="button" className="small" onClick={onLeave}>
              {t("demo_another")}
            </button>
          </span>
        </div>
      }
      slice={slice}
      control={control}
      province={province}
      onEdit={() => setEditing(true)}
      onPick={onPick}
      fileInput={fileInput}
    />
  );
}

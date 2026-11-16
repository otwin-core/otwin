/* "Your home": the householder's own home, its files and its results.
 *
 * A first visit is a welcome and the questions; after that, the dashboard.
 * Nothing here is ever touched by the Demo section.
 */
import { useState } from "react";

import { useT } from "../i18n";
import { Block } from "./bits";
import { Dashboard } from "./Dashboard";
import { Onboarding } from "./Onboarding";

export function YourHome({ slice, control, questions, province, onPick, fileInput, onDemo }) {
  const { t } = useT();
  const [editing, setEditing] = useState(false);

  if (!slice.onboarded || editing) {
    if (!slice.onboarded && !editing) {
      return (
        <div>
          <h1>{t("welcome_title")}</h1>
          <p className="lead">{t("welcome_lead")}</p>
          <p>
            <button type="button" className="primary big" id="start" onClick={() => setEditing(true)}>
              {t("welcome_start")}
            </button>
          </p>
          <p className="small">{t("welcome_time")}</p>
          <Block colour="yellow">
            <h3>{t("welcome_example")}</h3>
            <p className="small">{t("demo_lead")}</p>
            <button type="button" onClick={onDemo}>
              {t("nav_demo")}
            </button>
          </Block>
        </div>
      );
    }
    return (
      <Onboarding
        questions={questions}
        answers={slice.answers}
        fetchHome={control.fetchHome}
        saveLabel={slice.onboarded ? t("save_changes") : t("go_home")}
        onCancel={slice.onboarded ? () => setEditing(false) : null}
        onSave={async (answers) => {
          setEditing(false);
          await control.setAnswers(answers);
        }}
      />
    );
  }

  return (
    <Dashboard
      title={t("your_home_title")}
      slice={slice}
      control={control}
      province={province}
      onEdit={() => setEditing(true)}
      onPick={onPick}
      fileInput={fileInput}
    />
  );
}

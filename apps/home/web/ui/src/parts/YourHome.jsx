/* "My home": the householder's homes.
 *
 *   My home      the name, the answer and where the money goes; two
 *                buttons under the title open the other two pages
 *   Calibration  the files (add, read, check, delete), what they cover,
 *                and what the fit found
 *   Simulation   the improvements, and the forecasts to come; it needs a
 *                calibration, and says so when there is none
 *   Help         what this is and what happens to your data
 *
 * A first visit is a welcome and the questions, on their own. Nothing here
 * is ever touched by the Demo section.
 */
import { useState } from "react";

import { useT } from "../i18n";
import { Block, Prompt } from "./bits";
import { Calibration } from "./Calibration";
import { Answer, HomeHead } from "./Dashboard";
import { Money, WhatIf } from "./Explore";
import { Help } from "./Help";
import { Onboarding } from "./Onboarding";
import { Simulation } from "./Simulation";

export const PAGES = ["home", "calibration", "simulation", "help"];

export function YourHome({
  homes,
  home,
  page,
  onPage,
  control,
  questions,
  province,
  onPick,
  fileInput,
  onStart,
  onAddHome,
  onDemoHome,
  engineReady,
  onPickHome,
  onRename,
  onDiscard,
}) {
  const { t } = useT();
  const [editing, setEditing] = useState(false);
  const [renaming, setRenaming] = useState(false);

  const others = homes.filter((h) => h.answers && h.id !== home?.id); // described homes to go back to
  if (!home || !home.onboarded || editing) {
    if (!editing) {
      return (
        <div>
          <h1>{t("welcome_title")}</h1>
          <p className="lead">{t("welcome_lead")}</p>
          <p>
            <button
              type="button"
              className="primary big"
              id="start"
              onClick={() => {
                onStart();
                setEditing(true);
              }}
            >
              {t("welcome_start")}
            </button>
          </p>
          <p className="small">{t("welcome_time")}</p>
          <Block colour="yellow">
            <h3>{t("welcome_demo_title")}</h3>
            <p className="small">{t("welcome_demo_lead")}</p>
            <div className="demos-row">
              {["gas_winter", "electric"].map((key) => (
                <button key={key} type="button" data-demo-home={key} disabled={!engineReady} onClick={() => onDemoHome(key)}>
                  {t(`demo_home_${key}`)}
                </button>
              ))}
            </div>
            {!engineReady ? <p className="small">{t("engine_starting")}</p> : null}
          </Block>
          {others.length ? (
            <p>
              <button
                type="button"
                className="plain"
                id="back-home"
                onClick={() => {
                  if (home && !home.answers) onDiscard(home.id); // a home never described
                  onPickHome(others[0].id);
                }}
              >
                {t("home_back_to", { name: others[0].name })}
              </button>
            </p>
          ) : null}
        </div>
      );
    }
    return (
      <Onboarding
        questions={questions}
        answers={home?.answers}
        fetchHome={control.fetchHome}
        saveLabel={home?.onboarded ? t("save_changes") : t("go_home")}
        onCancel={() => {
          setEditing(false);
          if (home && !home.answers) onDiscard(home.id); // a home never described
        }}
        onSave={async (answers) => {
          setEditing(false);
          onPage("home");
          await control.setAnswers(answers);
        }}
      />
    );
  }

  const { report, cards } = home;
  const estimate = home.home?.ok ? home.home.estimate : null;
  const head = (
    <HomeHead
      title={home.name}
      subtitle={home.home?.ok ? home.home.header : ""}
      onEdit={() => setEditing(true)}
      tools={
        <div className="homes-row">
          <label>
            {t("homes_pick")}{" "}
            <select id="home-pick" value={home.id} onChange={(e) => onPickHome(e.target.value)}>
              {homes
                .filter((h) => h.answers)
                .map((h) => (
                  <option key={h.id} value={h.id}>
                    {h.name}
                  </option>
                ))}
            </select>
          </label>
          <button type="button" className="small" id="rename-home" onClick={() => setRenaming(true)}>
            {t("home_rename")}
          </button>
          <button type="button" className="small" id="new-home" onClick={onAddHome}>
            {t("home_new")}
          </button>
        </div>
      }
    />
  );

  return (
    <>
      {page === "home" ? (
        <>
          {head}
          <div className="page-links">
            <button type="button" id="to-calibration" onClick={() => onPage("calibration")}>
              {t("page_calibration")} →
            </button>
          </div>
          <Answer slice={home} control={control} />
          <h2>{t("tab_money")}</h2>
          <Money report={report} estimate={estimate} />
        </>
      ) : null}

      {page === "calibration" ? (
        <Calibration
          home={home}
          control={control}
          onPick={onPick}
          fileInput={fileInput}
          onHome={() => onPage("home")}
          onSimulation={() => onPage("simulation")}
          onEdit={() => setEditing(true)}
          onDemoHome={onDemoHome}
          engineReady={engineReady}
        />
      ) : null}

      {page === "simulation" ? (
        report ? (
          <Simulation home={home} control={control} questions={questions} onDigitalHome={() => onPage("calibration")} />
        ) : (
          <>
            <h1>{t("page_simulation")}</h1>
            <div className="banner next">
              <p className="title">{t("sim_needs_title")}</p>
              <p>{t("sim_needs_calibration")}</p>
              <button type="button" className="act" id="sim-to-calibration" onClick={() => onPage("calibration")}>
                {t("page_calibration")} →
              </button>
            </div>
          </>
        )
      ) : null}

      {page === "help" ? <Help /> : null}

      <Prompt
        open={renaming}
        onOpenChange={setRenaming}
        title={t("home_rename_title")}
        label={t("home_name_label")}
        value={home.name}
        confirm={t("save")}
        cancel={t("cancel")}
        onConfirm={(name) => {
          setRenaming(false);
          if (name.trim()) onRename(home.id, name.trim());
        }}
      />
    </>
  );
}

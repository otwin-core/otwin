/* "Calibration", for a householder: a checklist, not a form.
 *
 * The model learns the home from the household's own bills and readings.
 * This page walks through what to add, one step per source, in the order
 * that matters, each in plain words: what it is, why it helps, where to
 * find it, and three ways to add it (a file or a photo, typed by hand, or a
 * demo to try). The kind is known from the step, so nothing is asked twice.
 * A result card at the end says what the model knows so far. "Lost? Start
 * again" is always at hand: undo one step, remove every file, or describe
 * the home again. Help is a question away, inline.
 */
import { useEffect, useRef, useState } from "react";

import { useT } from "../i18n";
import { readDocument, warp } from "../ocr/engine";
import { Chip, Confirm } from "./bits";
import { IndoorChart } from "./Charts";
import { Months } from "./Explore";
import { Framer } from "./Framer";
import { InvoiceReview } from "./InvoiceReview";

//  The steps, in the order they matter. `need` says when the step applies.
const STEPS = [
  { kind: "electricity", need: "required", bill: false },
  { kind: "weather", need: "auto", bill: false },
  { kind: "gas", need: "gas", bill: true },
  { kind: "water", need: "optional", bill: true },
  { kind: "thermometer", need: "optional", bill: false },
];
const COLOUR = { electricity: "#005bbb", weather: "#9a9a95", gas: "#e2231a", water: "#111111", thermometer: "#ffc72c" };

export function Calibration({ home, control, onPick, fileInput, onHome, onSimulation, onEdit, onDemoHome, engineReady }) {
  const { t, n } = useT();
  const { cards, report } = home;
  // from the answers themselves: right at once, before the engine has answered
  const a = home.answers || {};
  const usesGas = a.heating === "gas" || a.water === "boiler" || a.water === "gas" || a.cooking === "gas";
  const cardOf = (kind) => cards?.cards?.find((c) => c.kind === kind);
  const [confirm, setConfirm] = useState(null); // {title, text, action}
  const [lost, setLost] = useState(false);
  const rows = fileRows(home, control.summaries, cards);

  const resetStep = (kind) => ({
    title: t("lost_step_title", { what: t(`step_${kind}_name`) }),
    text: t("lost_step_text", { what: t(`step_${kind}_name`).toLowerCase() }),
    action: async () => {
      for (const r of rows.filter((x) => x.kind === kind)) await control.removeFile(r.id);
      for (const d of control.docs.filter((x) => x.hint === kind)) control.dismissDoc(d.id);
    },
  });
  const removeAll = {
    title: t("lost_all_title"),
    text: t("lost_all_text"),
    action: async () => {
      for (const r of rows) await control.removeFile(r.id);
      for (const d of control.docs) control.dismissDoc(d.id);
    },
  };

  const stateOf = (s) => stepState(s, cardOf(s.kind), usesGas, rows.filter((r) => r.kind === s.kind).length);
  const done = STEPS.filter((s) => stateOf(s) === "done").length;
  const applicable = STEPS.filter((s) => stateOf(s) !== "not_needed").length;

  return (
    <div className="cal">
      <div className="cal-head">
        <div>
          <h1>{t("cal_title")}</h1>
          <p className="lead">{t("cal_lead2")}</p>
        </div>
        <div className="lost">
          <button type="button" id="lost" className={lost ? "on" : ""} onClick={() => setLost((v) => !v)}>
            {t("reset_button")}
          </button>
          {lost ? (
            <div className="lost-menu" role="menu">
              <p className="small">{t("reset_lead")}</p>
              <button type="button" className="plain" id="lost-all" onClick={() => { setLost(false); setConfirm(removeAll); }}>
                {t("reset_all")}
              </button>
              <button type="button" className="plain" id="lost-edit" onClick={() => { setLost(false); onEdit(); }}>
                {t("reset_edit")}
              </button>
            </div>
          ) : null}
        </div>
      </div>

      <div className="progress" aria-label={t("cal_progress", { done, total: applicable })}>
        <span className="bar">
          <i style={{ width: `${(100 * done) / Math.max(applicable, 1)}%` }} />
        </span>
        <span className="small">{t("cal_progress", { done, total: applicable })}</span>
      </div>
      {fileInput}

      <ol className="steps">
        {STEPS.map((step, i) => (
          <Step
            key={step.kind}
            index={i + 1}
            step={step}
            state={stateOf(step)}
            card={cardOf(step.kind)}
            rows={rows.filter((r) => r.kind === step.kind)}
            docs={control.docs.filter((d) => d.hint === step.kind)}
            control={control}
            home={home}
            onPick={() => onPick(step.kind)}
            onReset={() => setConfirm(resetStep(step.kind))}
          />
        ))}
      </ol>

      <Result home={home} control={control} usesGas={usesGas} onHome={onHome} onSimulation={onSimulation} onDemoHome={onDemoHome} engineReady={engineReady} />

      <details className="cal-help">
        <summary>{t("cal_help_title")}</summary>
        {["cal_help_1", "cal_help_2", "cal_help_3", "cal_help_4"].map((k) => (
          <p key={k}>{t(k)}</p>
        ))}
      </details>

      <Confirm
        open={!!confirm}
        onOpenChange={(o) => !o && setConfirm(null)}
        title={confirm?.title || ""}
        text={confirm?.text || ""}
        confirm={t("lost_confirm")}
        cancel={t("cancel")}
        onConfirm={async () => {
          const c = confirm;
          setConfirm(null);
          await c.action();
        }}
      />
    </div>
  );
}

/* The result card: one short line on where things stand, and the one
   action to take. Building the model is a button, never automatic: the
   householder may still be adding files, and must be able to build again
   after changing one. */
function Result({ home, control, usesGas, onHome, onSimulation, onDemoHome, engineReady }) {
  const { t, n } = useT();
  const { cards, report, stale } = home;
  const working = control.task === "analyse";
  const warnings = cards?.warnings || [];
  const missing = missingStep(cards, usesGas);
  let state = "waiting";
  if (working) state = "working";
  else if (report && !stale) state = report.confidence === "more_data" ? "weak" : "done";
  else if (cards?.ready) state = report ? "stale" : "ready";
  return (
    <section className="result" data-state={state}>
      <span className="band" />
      <div className="inner">
        <p className="tile-label">{t("result_title")}</p>
        {working ? <p className="answer-text">{t("result_working", { s: n(control.seconds) })}</p> : null}
        {state === "waiting" ? <p className="answer-text">{missing ? t(`miss_${missing.what}`, { step: missing.step }) : t("result_waiting")}</p> : null}
        {state === "waiting" && !home.demo ? (
          <div className="no-bills">
            <p>{t("no_bills_yet")}</p>
            <div className="demos-row">
              {["gas_winter", "electric"].map((key) => (
                <button key={key} type="button" className="small" data-demo-home={key} disabled={!engineReady} onClick={() => onDemoHome(key)}>
                  {t(`demo_home_${key}`)}
                </button>
              ))}
            </div>
          </div>
        ) : null}
        {home.demo && !home.demoTouched ? <p className="small">{t("demo_home_note")}</p> : null}
        {state === "ready" ? <p className="answer-text">{t("result_ready")}</p> : null}
        {state === "stale" ? <p className="answer-text">{t("result_stale")}</p> : null}
        {state === "done" ? <p className="answer-text">{report.confidence_text}</p> : null}
        {state === "weak" ? (
          <p className="answer-text">{missing ? t(`miss_${missing.what}`, { step: missing.step }) : t("result_weak")}</p>
        ) : null}
        {warnings.map((w) => (
          <p key={w.kind} className="warning" data-warning={w.kind}>
            {w.text}
          </p>
        ))}
        {report && !working ? (
          <div className="fit-charts" data-fit-charts>
            <h3>{t("fit_charts_title")}</h3>
            <p className="small">{t("fit_charts_lead")}</p>
            <Months report={report} />
            {report.periods
              .filter((p) => p.indoor)
              .map((p) => (
                <IndoorChart key={p.label} points={p.indoor} title={report.periods.length > 1 ? t("indoor_week_of", { label: p.label }) : t("indoor_week")} />
              ))}
          </div>
        ) : null}
        <div className="actions" style={{ justifyContent: "flex-start" }}>
          {state === "ready" || state === "stale" || state === "weak" ? (
            <button type="button" className="primary" id="build" onClick={() => control.build()}>
              {report ? t("build_again") : t("build")}
            </button>
          ) : null}
          {report && !working ? (
            <>
              <button type="button" className={state === "done" ? "primary" : ""} id="result-sim" onClick={onSimulation}>
                {t("sim_go")} →
              </button>
              <button type="button" id="result-home" onClick={onHome}>
                {t("result_see_home")}
              </button>
            </>
          ) : null}
        </div>
      </div>
    </section>
  );
}

/* What is missing for a fit, as the step to go to: {what, step} or null. */
function missingStep(cards, usesGas) {
  if (!cards?.cards) return { what: "electricity", step: 1 };
  const st = Object.fromEntries(cards.cards.map((c) => [c.kind, c.status]));
  if (st.electricity === "empty") return { what: "electricity", step: 1 };
  if (st.electricity === "problem") return { what: "more_electricity", step: 1 };
  if (st.weather === "needs_ok" || st.weather === "waiting") return { what: "weather", step: 2 };
  if (usesGas && st.gas === "empty") return { what: "gas", step: 3 };
  return null;
}

/* done | todo | waiting | needs_ok | optional | not_needed */
function stepState(step, card, usesGas, files) {
  if (step.need === "gas" && !usesGas) return "not_needed";
  if (step.bill && files > 0) return "done"; // a bill is in: the step is done, whatever the fit makes of it yet
  if (!card) return step.need === "optional" ? "optional" : "todo";
  if (card.status === "ready") return "done";
  if (card.status === "needs_ok") return "needs_ok";
  if (card.status === "waiting") return "waiting";
  if (card.status === "problem") return "problem";
  return step.need === "optional" ? "optional" : "todo";
}

function Step({ index, step, state, card, rows, docs, control, home, onPick, onReset }) {
  const { t } = useT();
  const [typing, setTyping] = useState(false);
  const [howOpen, setHowOpen] = useState(false);
  const kind = step.kind;
  const chip =
    state === "done" ? ["step_done", "on"] : state === "not_needed" ? ["step_not_needed", ""] : state === "optional" ? ["step_optional", ""] : state === "needs_ok" ? ["step_needs_ok", "warn"] : state === "waiting" ? ["step_waiting", ""] : state === "problem" ? ["st_problem", "warn"] : ["step_todo", "bad"];
  const dim = state === "not_needed";
  return (
    <li className={`step ${dim ? "dim" : ""}`} data-step={kind} data-state={state}>
      <span className="num" style={{ background: COLOUR[kind] }}>{state === "done" ? "✓" : index}</span>
      <div className="step-body">
        <div className="step-head">
          <h3>{t(`step_${kind}_name`)}</h3>
          <Chip kind={chip[1]}>{t(chip[0])}</Chip>
        </div>
        <p>{t(`step_${kind}_why`)}</p>
        {dim ? <p className="small">{t("step_gas_not_needed")}</p> : null}

        {!dim && card?.lines?.length ? (
          <ul className="lines">
            {card.lines.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        ) : null}

        {!dim && kind === "weather" ? (
          <WeatherStep card={card} control={control} home={home} />
        ) : null}

        {!dim && kind !== "weather" ? (
          <div className="step-actions">
            <button type="button" className="primary" data-add={kind} onClick={onPick}>
              {t(step.bill ? "act_photo_or_file" : "act_file")}
            </button>
            {step.bill ? (
              <button type="button" data-type={kind} onClick={() => setTyping((v) => !v)}>
                {t("act_type")}
              </button>
            ) : null}
            <button type="button" className="plain how" data-how={kind} onClick={() => setHowOpen((v) => !v)}>
              {t("act_how")}
            </button>
          </div>
        ) : null}
        {howOpen ? (
          <div className="how-box">
            {t(`step_${kind}_how`).map((s) => (
              <p key={s}>{s}</p>
            ))}
          </div>
        ) : null}

        {typing && !dim ? (
          <InvoiceReview
            doc={{ name: t(`${kind}_bill_title_ui`), hint: kind, result: { kind, form: {}, fields: {}, sentence: t("type_bill_lead") } }}
            onAdd={async (k, bill) => {
              const out = await control.addBill(k, bill);
              if (out.status === "ok") setTyping(false);
              return out;
            }}
            onDiscard={() => setTyping(false)}
          />
        ) : null}
        {dim
          ? null
          : docs.map((doc) => (
              <Document key={doc.id} doc={doc} control={control} />
            ))}

        {rows.length ? (
          <ul className="filelist">
            {rows.map((f) => (
              <li key={f.id} className="file" data-file={f.name} data-status={f.status} data-kind={f.kind} data-enabled={String(f.enabled)}>
                {!f.bill ? (
                  <label className="use" title={t("use_in_fit")}>
                    <input type="checkbox" checked={f.enabled} onChange={() => control.toggleFile(f.id)} />
                  </label>
                ) : (
                  <span className="use" />
                )}
                <div className="file-body">
                  <div className="file-head">
                    <span className="file-name">{f.name}</span>
                    {f.status !== "ok" && f.status !== "busy" ? <Chip kind={f.status === "error" ? "bad" : "warn"}>{t(f.status === "error" ? "not_read" : "needs_help")}</Chip> : null}
                  </div>
                  {f.message ? <p className="file-msg">{f.message}</p> : null}
                </div>
                <button type="button" className="remove" title={t("remove")} aria-label={t("remove_file", { name: f.name })} onClick={() => control.removeFile(f.id)}>
                  ×
                </button>
              </li>
            ))}
          </ul>
        ) : null}
        {!dim && (rows.length || docs.length) ? (
          <p className="small">
            <button type="button" className="plain" data-reset={kind} onClick={onReset}>
              {t("step_reset")}
            </button>
          </p>
        ) : null}
      </div>
    </li>
  );
}

function WeatherStep({ card, control, home }) {
  const { t } = useT();
  const province = home.home?.ok ? home.home.header.split(" · ")[0] : "";
  if (!card) return null;
  if (card.status === "needs_ok") {
    return (
      <div className="step-actions">
        <button type="button" className="primary" id="get-weather" disabled={control.weatherBusy} onClick={() => control.fetchWeather(card.request)}>
          {t("act_weather")}
        </button>
        <span className="small">
          {control.weatherMessage ? (control.weatherMessage === "fetching" ? t("weather_fetching") : t("weather_failed", { message: control.weatherMessage })) : t("weather_consent", { province })}
        </span>
      </div>
    );
  }
  if (card.status === "waiting") return <p className="small">{t("weather_waiting")}</p>;
  if (card.status === "ready" && !card.lines.length) return <p className="small">{t("weather_auto")}</p>;
  return null;
}

/* The files of this home by the kind the householder gave on the step. */
function fileRows(home, summaries, cards) {
  const engineKind = new Map();
  for (const card of cards?.cards || []) for (const f of card.files || []) engineKind.set(f.id, card.kind);
  const rows = [];
  for (const f of home.files || []) {
    const s = summaries.get(f.id) || {};
    rows.push({ id: f.id, name: f.name, kind: f.kind || engineKind.get(f.id) || "electricity", status: s.status || (f.enabled === false ? "ok" : "busy"), message: f.enabled === false ? "" : s.message, enabled: f.enabled !== false });
  }
  for (const b of home.bills || []) {
    const s = summaries.get(b.id) || {};
    rows.push({ id: b.id, name: s.name || b.kind, kind: b.kind, status: s.status || "ok", message: s.message, enabled: true, bill: true });
  }
  return rows;
}

/* One dropped document on its way in: framed (a photo), read, reviewed. */
function Document({ doc, control }) {
  const { t } = useT();
  const [progress, setProgress] = useState("");
  const [frameCanvas, setFrameCanvas] = useState(null);
  const frameAnswer = useRef(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current || doc.state !== "new") return;
    started.current = true;
    control.updateDoc(doc.id, { state: "reading" });
    const frame = (canvas) =>
      new Promise((resolve) => {
        frameAnswer.current = resolve;
        setFrameCanvas(canvas);
      });
    (async () => {
      try {
        const out = await readDocument({ name: doc.name, bytes: doc.bytes }, { onProgress: (key, values) => setProgress(t(key, values || {})), frame });
        if (out.cancelled) {
          control.dismissDoc(doc.id);
          return;
        }
        const result = await control.readInvoice(
          out.pages.map((p) => p.words),
          doc.hint,
        );
        control.updateDoc(doc.id, { state: "review", pages: out.pages, result: { ...result, kind: doc.hint || result.kind } });
      } catch (e) {
        control.updateDoc(doc.id, { state: "error", error: e.message });
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc.id]);

  if (doc.state === "review") {
    return (
      <InvoiceReview
        doc={doc}
        onAdd={async (kind, bill) => {
          const out = await control.addBill(kind, bill);
          if (out.status === "ok") control.dismissDoc(doc.id);
          return out;
        }}
        onDiscard={() => control.dismissDoc(doc.id)}
      />
    );
  }
  return (
    <section className="doc-review" data-doc={doc.name} data-state={doc.state}>
      <div className="doc-head">
        <div>
          <p className="tile-label">{t("doc_reading")}</p>
          <p className="doc-name">{doc.name}</p>
          {doc.state === "error" ? (
            <p className="error">
              {t("doc_failed")} {doc.error}
            </p>
          ) : (
            <p className="small">{progress}</p>
          )}
        </div>
        {doc.state === "error" ? (
          <button type="button" className="small" onClick={() => control.dismissDoc(doc.id)}>
            {t("doc_discard")}
          </button>
        ) : null}
      </div>
      {frameCanvas ? (
        <Framer
          canvas={frameCanvas}
          onCancel={() => {
            frameAnswer.current?.(null);
            setFrameCanvas(null);
          }}
          onRead={(corners) => {
            const answer = frameAnswer.current;
            setFrameCanvas(null);
            answer?.(corners ? warp(frameCanvas, corners) : frameCanvas);
          }}
        />
      ) : null}
    </section>
  );
}

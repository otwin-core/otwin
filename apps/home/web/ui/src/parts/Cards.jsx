/* The data, as five cards: electricity, gas, water, thermometer, weather.
 *
 * Each says what it holds and what it would add. Files can be dropped
 * anywhere on the page; they land in the card they belong to. Gas and water
 * bills can be typed in. The weather is fetched once it is allowed.
 */
import { useRef, useState } from "react";

import { useT } from "../i18n";
import { Chip } from "./bits";

const STATUS_CHIP = {
  ready: ["st_ready", "on"],
  empty: ["st_empty", ""],
  problem: ["st_problem", "warn"],
  needs_ok: ["st_needs_ok", "warn"],
  waiting: ["st_waiting", ""],
  not_needed: ["st_not_needed", ""],
};

export function DataCards({ cards, summaries, province, onPick, onRemove, onMap, onBill, weather }) {
  const { t } = useT();
  if (!cards?.cards) return null;
  const known = new Set(
    [...cards.cards.flatMap((c) => c.files || []), ...(cards.other || [])].map((f) => f.id),
  );
  const reading = [...summaries.values()].filter((f) => f.status === "busy" && !known.has(f.id));
  const other = [...reading, ...(cards.other || []).map((f) => merge(f, summaries))];
  return (
    <>
      <div className="cards">
        {cards.cards.map((card) => (
          <Card
            key={card.kind}
            card={card}
            summaries={summaries}
            province={province}
            onPick={onPick}
            onRemove={onRemove}
            onMap={onMap}
            onBill={onBill}
            weather={weather}
          />
        ))}
      </div>
      {other.length ? (
        <>
          <h3 style={{ marginTop: 28 }}>{t("other_files")}</h3>
          <ul className="files">
            {other.map((f) => (
              <FileLine key={f.id} file={f} onRemove={onRemove} onMap={onMap} />
            ))}
          </ul>
        </>
      ) : null}
    </>
  );
}

/* The engine's description (in the current language) plus what only the
   page knows: the column choice and its error in the mapper. */
function merge(file, summaries) {
  const local = summaries.get(file.id) || {};
  return {
    ...file,
    choice: local.choice,
    error: file.status === "needs_mapping" ? local.error : undefined,
  };
}

function Card({ card, summaries, province, onPick, onRemove, onMap, onBill, weather }) {
  const { t } = useT();
  const [form, setForm] = useState(false);
  const [chipKey, chipKind] = STATUS_CHIP[card.status] || STATUS_CHIP.empty;
  const files = (card.files || []).map((f) => merge(f, summaries));
  const isWeather = card.kind === "weather";
  const hint =
    card.kind === "gas" && card.status === "not_needed" ? "add_gas_not_needed" : `add_${card.kind}`;
  return (
    <section className="card" data-kind={card.kind} data-status={card.status}>
      <div className="band" />
      <div className="inner">
        <div className="card-head">
          <h3>{t(`card_${card.kind}`)}</h3>
          <Chip kind={chipKind}>{t(chipKey)}</Chip>
        </div>
        {card.lines.length ? (
          <ul className="lines">
            {card.lines.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        ) : null}
        {card.status === "empty" || card.status === "not_needed" ? (
          <p className="small">{t(hint)}</p>
        ) : null}
        {isWeather ? (
          <WeatherBits card={card} province={province} weather={weather} />
        ) : null}
        {card.kind === "electricity" ? (
          <details className="guide">
            <summary>{t("how_datadis")}</summary>
            <ol>
              {t("datadis_steps").map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ol>
          </details>
        ) : null}
        {form ? (
          <BillForm
            kind={card.kind}
            onAdd={async (bill) => {
              const out = await onBill(card.kind, bill);
              if (out.status === "ok") setForm(false);
              return out;
            }}
          />
        ) : null}
        {files.length ? (
          <details className="card-files" open={files.some((f) => f.status !== "ok")}>
            <summary>{t(files.length === 1 ? "files_one" : "files_n", { n: files.length })}</summary>
            <ul className="files">
              {files.map((f) => (
                <FileLine key={f.id} file={f} onRemove={onRemove} onMap={onMap} />
              ))}
            </ul>
          </details>
        ) : null}
        <div className="card-actions">
          {isWeather || card.status === "not_needed" ? null : (
            <button type="button" className="small" onClick={onPick}>
              {t("act_add")}
            </button>
          )}
          {(card.kind === "gas" || card.kind === "water") && card.status !== "not_needed" ? (
            <button type="button" className="small" onClick={() => setForm((v) => !v)}>
              {t("act_type_bill")}
            </button>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function WeatherBits({ card, province, weather }) {
  const { t } = useT();
  return (
    <>
      {card.status === "needs_ok" ? (
        <>
          <p className="small">{t("weather_consent", { province })}</p>
          <button
            type="button"
            className="small primary"
            disabled={weather.busy}
            onClick={() => weather.fetch(card.request)}
          >
            {t("act_weather")}
          </button>
        </>
      ) : null}
      {card.status === "waiting" ? <p className="small">{t("weather_waiting")}</p> : null}
      {card.status === "ready" && !card.lines.length ? (
        <p className="small">{t("weather_auto")}</p>
      ) : null}
      {weather.message ? (
        <p className="small">
          {weather.message === "fetching"
            ? t("weather_fetching")
            : t("weather_failed", { message: weather.message })}
        </p>
      ) : null}
    </>
  );
}

function FileLine({ file, onRemove, onMap }) {
  const { t } = useT();
  const tag = { needs_mapping: "needs_help", error: "not_read", busy: "st_reading" }[file.status];
  return (
    <li className="file" data-file={file.name} data-status={file.status}>
      <div className="file-head">
        <span className="file-name">{file.name}</span>
        <span>
          {tag ? <Chip kind={file.status === "error" ? "bad" : "warn"}>{t(tag)}</Chip> : null}
          <button
            type="button"
            className="remove"
            title={t("remove")}
            aria-label={t("remove_file", { name: file.name })}
            onClick={() => onRemove(file.id)}
          >
            ×
          </button>
        </span>
      </div>
      {file.message ? <p className="file-msg">{file.message}</p> : null}
      {file.status === "needs_mapping" && file.mapping ? (
        <Mapper file={file} onMap={onMap} />
      ) : null}
    </li>
  );
}

function Mapper({ file, onMap }) {
  const { t } = useT();
  const guess = { ...file.mapping.guess, ...(file.choice || {}) };
  const [choice, setChoice] = useState(guess);
  const unitsFor = (q) => file.mapping.quantities.find((x) => x.value === q)?.units || [];
  const set = (k, v) =>
    setChoice((c) => ({ ...c, [k]: v, ...(k === "quantity" ? { unit: unitsFor(v)[0] } : {}) }));
  return (
    <div className="mapper">
      <p className="tile-label">{t("mapper_title")}</p>
      <div className="preview">
        <table>
          <tbody>
            <tr>
              {file.mapping.headers.map((h) => (
                <th key={h}>{h}</th>
              ))}
            </tr>
            {file.mapping.preview.map((row, i) => (
              <tr key={i}>
                {row.map((c, j) => (
                  <td key={j}>{c}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <label>
        {t("mapper_time")}
        <select value={choice.time || ""} onChange={(e) => set("time", e.target.value)}>
          {file.mapping.headers.map((h) => (
            <option key={h}>{h}</option>
          ))}
        </select>
      </label>
      <label>
        {t("mapper_value")}
        <select value={choice.value || ""} onChange={(e) => set("value", e.target.value)}>
          {file.mapping.headers.map((h) => (
            <option key={h}>{h}</option>
          ))}
        </select>
      </label>
      <label>
        {t("mapper_what")}
        <select value={choice.quantity} onChange={(e) => set("quantity", e.target.value)}>
          {file.mapping.quantities.map((q) => (
            <option key={q.value} value={q.value}>
              {t(`mq_${q.value}`)}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("mapper_unit")}
        <select value={choice.unit} onChange={(e) => set("unit", e.target.value)}>
          {unitsFor(choice.quantity).map((u) => (
            <option key={u}>{u}</option>
          ))}
        </select>
      </label>
      {choice.quantity.endsWith("temperature") ? null : (
        <label className="check">
          <input
            type="checkbox"
            checked={!!choice.cumulative}
            onChange={(e) => set("cumulative", e.target.checked)}
          />
          {t("mapper_counter")}
        </label>
      )}
      {file.error ? <p className="error">{file.error}</p> : null}
      <p>
        <button
          type="button"
          className="primary small"
          onClick={() => onMap(file.id, { ...choice, label: "start" })}
        >
          {t("mapper_go")}
        </button>
      </p>
    </div>
  );
}

function BillForm({ kind, onAdd }) {
  const { t } = useT();
  const [message, setMessage] = useState("");
  const form = useRef(null);
  const field = (key, name, type = "text") => (
    <label key={name}>
      {t(key)}
      <input type={type} name={name} inputMode={type === "text" ? "decimal" : undefined} />
    </label>
  );
  return (
    <form className="billform" ref={form} onSubmit={(e) => e.preventDefault()}>
      <p className="tile-label">{t(`bill_title_${kind}`)}</p>
      {kind === "gas" ? <p className="small">{t("bill_help")}</p> : null}
      <div className="grid">
        {field("bill_start", "start", "date")}
        {field("bill_end", "end", "date")}
        {field("bill_m3", "m3")}
        {kind === "gas" ? field("bill_fc", "fc") : null}
        {kind === "gas" ? field("bill_pcs", "pcs") : null}
        {kind === "gas" ? field("bill_kwh", "kwh") : null}
        {field("bill_eur", "eur")}
      </div>
      {message ? <p className="error">{message}</p> : null}
      <p>
        <button
          type="button"
          className="primary small"
          onClick={async () => {
            const bill = {};
            for (const name of ["start", "end", "m3", "fc", "pcs", "kwh", "eur"]) {
              const input = form.current.elements[name];
              if (input) bill[name] = input.value.trim();
            }
            const out = await onAdd(bill);
            setMessage(out.status === "ok" ? "" : out.message);
          }}
        >
          {t("bill_add")}
        </button>
      </p>
    </form>
  );
}

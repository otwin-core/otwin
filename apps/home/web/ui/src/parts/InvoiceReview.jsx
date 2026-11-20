/* What was read from a bill, for the householder to check before it is
 * added: the sentence, the page as read, and the fields prefilled, each
 * with the words it came from. A low-confidence field is marked. Nothing is
 * added until "Add this bill" is pressed.
 */
import { useState } from "react";

import { useT } from "../i18n";
import { Chip } from "./bits";

const FIELDS = {
  electricity: ["start", "end", "kwh", "eur"],
  gas: ["start", "end", "m3", "fc", "pcs", "kwh", "eur"],
  water: ["start", "end", "m3", "eur"],
};
const LABEL = { start: "bill_start", end: "bill_end", m3: "bill_m3", fc: "bill_fc", pcs: "bill_pcs", kwh: "bill_kwh", eur: "bill_eur" };

export function InvoiceReview({ doc, onAdd, onDiscard }) {
  const { t } = useT();
  const read = doc.result || {};
  const [kind, setKind] = useState(doc.hint || read.kind || "gas");
  const [form, setForm] = useState(() => ({ start: "", end: "", kwh: "", m3: "", fc: "", pcs: "", eur: "", ...(read.form || {}) }));
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const fields = read.fields || {};
  const preview = doc.pages?.find((p) => p.preview)?.preview;
  return (
    <section className="doc-review" data-doc={doc.name}>
      <div className="doc-head">
        <div>
          <p className="tile-label">{t("doc_review_title")}</p>
          <p className="doc-name">{doc.name}</p>
          <p>{read.sentence || t("inv_nothing")}</p>
          {(read.notes || []).map((n) => (
            <p key={n} className="error">
              {n}
            </p>
          ))}
        </div>
        {preview ? <img className="doc-preview" src={preview} alt="" /> : null}
      </div>
      <p className="small kind-note" data-kind={kind}>
        {t("doc_kind", { kind: t(`card_${kind}`) })}{" "}
        {!doc.hint ? (
          <span className="kind-pick">
            {["electricity", "gas", "water"].filter((k) => k !== kind).map((k) => (
              <button key={k} type="button" className="plain" data-kind={k} onClick={() => setKind(k)}>
                {t("doc_kind_change", { kind: t(`card_${k}`) })}
              </button>
            ))}
          </span>
        ) : null}
      </p>
      <form
        className="billform"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          const bill = {};
          for (const f of FIELDS[kind]) bill[f] = (form[f] || "").trim();
          const out = await onAdd(kind, bill);
          setBusy(false);
          setMessage(out?.status === "ok" ? "" : out?.message || t("doc_failed"));
        }}
      >
        <div className="grid">
          {FIELDS[kind].map((f) => {
            const ev = fields[f];
            const low = ev && ev.confidence < 0.7;
            return (
              <label key={f} data-field={f} data-low={String(!!low)}>
                {t(LABEL[f])}
                <input type={f === "start" || f === "end" ? "date" : "text"} inputMode="decimal" value={form[f] || ""} onChange={(e) => setForm((s) => ({ ...s, [f]: e.target.value }))} />
                {ev?.evidence ? (
                  <span className="evidence">
                    {low ? <Chip kind="warn">{t("check_this")}</Chip> : null} {t("read_from", { text: ev.evidence })}
                  </span>
                ) : (
                  <span className="evidence muted">{t("not_read")}</span>
                )}
              </label>
            );
          })}
        </div>
        {message ? <p className="error">{message}</p> : null}
        <div className="actions">
          <button type="button" onClick={onDiscard}>
            {t("doc_discard")}
          </button>
          <button type="submit" className="primary" id="doc-add" disabled={busy}>
            {t("doc_add")}
          </button>
        </div>
      </form>
    </section>
  );
}

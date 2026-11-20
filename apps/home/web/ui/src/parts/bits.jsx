/* The small pieces every section is built from.
 *
 * Radix gives the behaviour (keyboard, focus, roles); the look is ours:
 * squares, circles, thick rules, flat colour.
 */
import * as Dialog from "@radix-ui/react-dialog";
import * as Select from "@radix-ui/react-select";
import { useEffect, useState } from "react";

import { useT } from "../i18n";
import { Gauge, OptionRow, Segmented, Slider, Switch } from "./controls";

export function Block({ colour = "", children, ...rest }) {
  return (
    <section className={`block ${colour}`} {...rest}>
      <div className="band" />
      <div className="inner">{children}</div>
    </section>
  );
}

export function Chip({ kind = "", children, ...rest }) {
  return (
    <span className={`chip ${kind}`} {...rest}>
      {children}
    </span>
  );
}

/* How well the home keeps the heat, as a traffic light.
 *
 * The engine grades the envelope on the certificate's A–G scale, which is
 * not an official certificate, so the page never shows the letter: it folds
 * it into three colours. Green keeps the heat well (A–C), orange fairly
 * (D–E), red loses it fast (F–G).
 */
export const BAND_COLOUR = { green: "#0f8a3c", orange: "#f28c28", red: "#e2231a" };

export function bandOf(letter) {
  if (!letter || letter === "–") return null;
  if ("ABC".includes(letter)) return "green";
  if ("DE".includes(letter)) return "orange";
  return "red";
}

export function Lights({ band, small }) {
  return (
    <div className={`lights ${small ? "sm" : ""}`} data-band={band || ""} aria-hidden="true">
      {["red", "orange", "green"].map((b) => (
        <span key={b} className={`light ${b} ${b === band ? "on" : ""}`} />
      ))}
    </div>
  );
}

export function ConfBar({ level }) {
  return (
    <div className="conf" data-level={level}>
      {[1, 2, 3].map((i) => (
        <span key={i} className={i <= level ? "on" : ""} />
      ))}
    </div>
  );
}

/* A working line: what is happening, and for how long. */
export function Status({ text }) {
  return (
    <p className="status" role="status">
      <span className="bar">
        <i />
      </span>
      <span>{text}</span>
    </p>
  );
}

/* One question, drawn with the control its kind calls for: a gauge for a
   temperature, a slider for a number, a switch, three options side by
   side, a row of buttons, or a list for the provinces. The same controls
   serve a simulation (controls.jsx). */
export function Question({ question, value, onChange }) {
  const { id, label, help, options, kind } = question;
  const asSelect = kind === "single" && options.length > 8;
  const legacy = (v) => {
    // an old named answer ("m", "pre1980") shown on a slider: its number
    if (id === "size") return { s: 50, m: 75, l: 105, xl: 140 }[v] ?? Number(v);
    if (id === "built") return { pre1980: 1965, "1980_2006": 1995, post2007: 2015 }[v] ?? Number(v);
    if (id === "heating_power") return v === "auto" ? 0 : Number(v);
    return Number(v);
  };
  return (
    <fieldset data-question={id} data-kind={kind}>
      <legend>{label}</legend>
      {help ? <p className="help">{help}</p> : null}
      {kind === "gauge" ? (
        <Gauge name={id} value={legacy(value)} min={question.minimum} max={question.maximum} step={question.step} onChange={(v) => onChange(String(v))} />
      ) : kind === "slider" ? (
        <Slider
          name={id}
          value={legacy(value)}
          min={question.minimum}
          max={question.maximum}
          step={question.step}
          unit={question.unit}
          zeroLabel={id === "heating_power" ? options[0]?.label : undefined}
          onChange={(v) => onChange(String(v))}
        />
      ) : kind === "switch" ? (
        <Switch name={id} checked={value === options[1].value} label={value === options[1].value ? options[1].label : options[0].label} onChange={(on) => onChange(on ? options[1].value : options[0].value)} />
      ) : asSelect ? (
        <Picker value={value} options={options} label={label} onChange={onChange} name={id} />
      ) : kind === "multi" ? (
        <div className="switches">
          {options.map((o) => {
            const on = value.includes(o.value);
            return <Switch key={o.value} name={`${id}.${o.value}`} checked={on} label={o.label} onChange={(next) => onChange(next ? [...value, o.value] : value.filter((v) => v !== o.value))} />;
          })}
        </div>
      ) : options.length <= 3 ? (
        <Segmented name={id} options={options} value={value} onChange={onChange} />
      ) : (
        <OptionRow name={id} options={options} value={value} onChange={onChange} />
      )}
    </fieldset>
  );
}

/* A long list (the provinces): Radix Select, drawn as a plain field. */
export function Picker({ value, options, label, onChange, name }) {
  return (
    <Select.Root value={value} onValueChange={onChange} name={name}>
      <Select.Trigger className="btn" aria-label={label}>
        <Select.Value />
        <Select.Icon> ▾</Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Content className="dialog" position="popper" sideOffset={4}>
          <Select.Viewport>
            {options.map((o) => (
              <Select.Item key={o.value} value={o.value} className="choice">
                <Select.ItemText>{o.label}</Select.ItemText>
              </Select.Item>
            ))}
          </Select.Viewport>
        </Select.Content>
      </Select.Portal>
    </Select.Root>
  );
}

/* A question asked before something is undone. */
export function Confirm({ open, onOpenChange, title, text, confirm, cancel, onConfirm }) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="overlay" />
        <Dialog.Content className="dialog">
          <Dialog.Title>{title}</Dialog.Title>
          <Dialog.Description>{text}</Dialog.Description>
          <div className="actions">
            <Dialog.Close asChild>
              <button type="button">{cancel}</button>
            </Dialog.Close>
            <button type="button" className="primary" onClick={onConfirm}>
              {confirm}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/* A question with one line to type: the name of a home, say. */
export function Prompt({ open, onOpenChange, title, label, value, confirm, cancel, onConfirm }) {
  const [text, setText] = useState(value || "");
  useEffect(() => {
    if (open) setText(value || "");
  }, [open, value]);
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="overlay" />
        <Dialog.Content className="dialog" aria-describedby={undefined}>
          <Dialog.Title>{title}</Dialog.Title>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              onConfirm(text);
            }}
          >
            <label className="field">
              {label}
              <input id="prompt-input" type="text" value={text} autoFocus onChange={(e) => setText(e.target.value)} />
            </label>
            <div className="actions">
              <Dialog.Close asChild>
                <button type="button">{cancel}</button>
              </Dialog.Close>
              <button type="submit" className="primary" disabled={!text.trim()}>
                {confirm}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/* Everything about the page itself, behind the gear: the language, the
   homes this browser keeps (name them, delete one), and the way to forget
   it all. */
export function Settings({ open, onOpenChange, lang, onLang, homes, current, onRename, onRemove, onForget }) {
  const { t } = useT();
  const [removing, setRemoving] = useState(null);
  return (
    <>
      <Dialog.Root open={open} onOpenChange={onOpenChange}>
        <Dialog.Portal>
          <Dialog.Overlay className="overlay" />
          <Dialog.Content className="dialog settings" aria-describedby={undefined}>
            <Dialog.Title>{t("settings")}</Dialog.Title>
            <section className="setting">
              <label className="lang">
                {t("language")}{" "}
                <select id="lang" aria-label="Language / Idioma" value={lang} onChange={(e) => onLang(e.target.value)}>
                  <option value="en">English</option>
                  <option value="es">Español</option>
                </select>
              </label>
            </section>
            <section className="setting">
              <p className="tile-label">{t("settings_homes")}</p>
              {homes.length ? (
                <ul className="homes-list">
                  {homes.map((h) => (
                    <li key={h.id} data-current={String(h.id === current)}>
                      <input
                        type="text"
                        aria-label={t("home_name_label")}
                        value={h.name}
                        onChange={(e) => onRename(h.id, e.target.value)}
                        onBlur={(e) => !e.target.value.trim() && onRename(h.id, t("home_default_name"))}
                      />
                      <button type="button" className="small" onClick={() => setRemoving(h)}>
                        {t("settings_delete_home")}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="small">{t("settings_no_homes")}</p>
              )}
            </section>
            <section className="setting">
              <p className="small">{t("saved_here")}</p>
              <button type="button" id="forget" onClick={onForget}>
                {t("forget_all")}
              </button>
            </section>
            <div className="actions" style={{ justifyContent: "flex-end" }}>
              <Dialog.Close asChild>
                <button type="button" className="primary" id="settings-close">
                  {t("close")}
                </button>
              </Dialog.Close>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
      <Confirm
        open={!!removing}
        onOpenChange={(o) => !o && setRemoving(null)}
        title={t("settings_delete_home")}
        text={removing ? t("delete_home_confirm", { name: removing.name }) : ""}
        confirm={t("settings_delete_home")}
        cancel={t("cancel")}
        onConfirm={() => {
          onRemove(removing.id);
          setRemoving(null);
        }}
      />
    </>
  );
}

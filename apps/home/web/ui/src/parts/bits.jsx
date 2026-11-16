/* The small pieces every section is built from.
 *
 * Radix gives the behaviour (keyboard, focus, roles); the look is ours:
 * squares, circles, thick rules, flat colour.
 */
import * as Checkbox from "@radix-ui/react-checkbox";
import * as Dialog from "@radix-ui/react-dialog";
import * as RadioGroup from "@radix-ui/react-radio-group";
import * as Select from "@radix-ui/react-select";

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

export function Letter({ letter, small }) {
  return <div className={`letter ${small ? "sm" : ""} l-${letter}`}>{letter}</div>;
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

/* One question: radio buttons, checkboxes or, for a long list, a select. */
export function Question({ question, value, onChange }) {
  const { id, label, help, options, kind } = question;
  const asSelect = kind === "single" && options.length > 8;
  return (
    <fieldset data-question={id}>
      <legend>{label}</legend>
      {help ? <p className="help">{help}</p> : null}
      {asSelect ? (
        <Picker value={value} options={options} label={label} onChange={onChange} name={id} />
      ) : kind === "multi" ? (
        <div className="choices">
          {options.map((o) => {
            const on = value.includes(o.value);
            return (
              <label key={o.value} className="choice" data-kind="checkbox" data-on={String(on)}>
                <Checkbox.Root
                  className="box"
                  name={id}
                  value={o.value}
                  checked={on}
                  onCheckedChange={(next) =>
                    onChange(next ? [...value, o.value] : value.filter((v) => v !== o.value))
                  }
                />
                <span>{o.label}</span>
              </label>
            );
          })}
        </div>
      ) : (
        <RadioGroup.Root className="choices" name={id} value={value} onValueChange={onChange}>
          {options.map((o) => (
            <label key={o.value} className="choice" data-kind="radio" data-on={String(value === o.value)}>
              <RadioGroup.Item className="box" value={o.value} />
              <span>{o.label}</span>
            </label>
          ))}
        </RadioGroup.Root>
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

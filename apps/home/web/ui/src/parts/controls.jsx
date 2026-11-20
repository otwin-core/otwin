/* The controls, shared by the questions about a home and by a simulation:
 * the same thing is always set the same way.
 *
 *   Gauge      a temperature, on a semicircle from blue to red
 *   Slider     a number with a unit (m², kW, people, a year, € per kWh)
 *   Switch     off or on
 *   Segmented  three options or fewer, side by side
 *   OptionRow  more options, a row of labelled buttons
 *
 * Bauhaus like the rest: squares, circles, thick rules, flat colour.
 */
import { useId, useRef } from "react";

export function Segmented({ options, value, onChange, name }) {
  return (
    <div className="segmented" role="radiogroup" data-name={name}>
      {options.map((o) => (
        <button key={o.value} type="button" role="radio" aria-checked={value === o.value} data-value={o.value} className={value === o.value ? "on" : ""} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function OptionRow({ options, value, onChange, name }) {
  return (
    <div className="optrow" role="radiogroup" data-name={name}>
      {options.map((o) => (
        <button key={o.value} type="button" role="radio" aria-checked={value === o.value} data-value={o.value} className={value === o.value ? "on" : ""} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

/* on/off; `options` are [off, on] when the value is a word, not a boolean */
export function Switch({ checked, onChange, label, name }) {
  return (
    <button type="button" role="switch" aria-checked={checked} className={`switch ${checked ? "on" : ""}`} data-name={name} onClick={() => onChange(!checked)}>
      <span className="knob" />
      {label ? <span className="switch-label">{label}</span> : null}
    </button>
  );
}

export function Slider({ value, onChange, min, max, step = 1, unit = "", format, name, zeroLabel }) {
  const id = useId();
  const v = Number(value);
  const shown = format ? format(v) : zeroLabel && v === 0 ? zeroLabel : `${Number.isInteger(step) ? Math.round(v) : v}${unit ? ` ${unit}` : ""}`;
  return (
    <div className="slider" data-name={name}>
      <input id={id} type="range" min={min} max={max} step={step} value={v} onChange={(e) => onChange(Number(e.target.value))} />
      <output htmlFor={id} className="slider-value">
        {shown}
      </output>
    </div>
  );
}

/* A temperature on a semicircle: drag or click along the arc, or use the
   arrow keys. The arc goes from blue (cold) to red (hot); the needle marks
   the value. */
export function Gauge({ value, onChange, min = 16, max = 26, step = 0.5, name }) {
  const ref = useRef(null);
  const W = 240;
  const R = 96;
  const cx = W / 2;
  const cy = 112;
  const v = Math.min(max, Math.max(min, Number(value)));
  const frac = (v - min) / (max - min);
  const angle = Math.PI * (1 - frac); // π at min (left) → 0 at max (right)
  const nx = cx + R * Math.cos(angle);
  const ny = cy - R * Math.sin(angle);
  const gradId = `g${name || "gauge"}`;
  const snap = (x) => Math.round(x / step) * step;
  const fromPoint = (clientX, clientY) => {
    const box = ref.current.getBoundingClientRect();
    const x = ((clientX - box.left) / box.width) * W - cx;
    const y = cy - ((clientY - box.top) / box.height) * (cy + 20);
    let a = Math.atan2(Math.max(y, 0), x); // 0..π
    a = Math.min(Math.PI, Math.max(0, a));
    const f = 1 - a / Math.PI;
    onChange(Math.min(max, Math.max(min, snap(min + f * (max - min)))));
  };
  const onPointerDown = (e) => {
    e.preventDefault();
    ref.current.setPointerCapture(e.pointerId);
    fromPoint(e.clientX, e.clientY);
  };
  const onPointerMove = (e) => {
    if (e.buttons & 1) fromPoint(e.clientX, e.clientY);
  };
  const onKey = (e) => {
    if (e.key === "ArrowRight" || e.key === "ArrowUp") onChange(Math.min(max, snap(v + step)));
    if (e.key === "ArrowLeft" || e.key === "ArrowDown") onChange(Math.max(min, snap(v - step)));
  };
  const ticks = [];
  for (let t = min; t <= max + 1e-9; t += (max - min) / 10) ticks.push(t);
  return (
    <div className="gauge" data-name={name}>
      <svg
        ref={ref}
        viewBox={`0 0 ${W} ${cy + 20}`}
        role="slider"
        tabIndex={0}
        aria-valuemin={min}
        aria-valuemax={max}
        aria-valuenow={v}
        aria-label={`${v} °C`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onKeyDown={onKey}
      >
        <defs>
          <linearGradient id={gradId} x1="0" x2="1" y1="0" y2="0">
            <stop offset="0" stopColor="#005bbb" />
            <stop offset="0.5" stopColor="#ffc72c" />
            <stop offset="1" stopColor="#e2231a" />
          </linearGradient>
        </defs>
        <path d={`M ${cx - R} ${cy} A ${R} ${R} 0 0 1 ${cx + R} ${cy}`} fill="none" stroke={`url(#${gradId})`} strokeWidth="18" strokeLinecap="butt" />
        {ticks.map((t) => {
          const a = Math.PI * (1 - (t - min) / (max - min));
          return <line key={t} x1={cx + (R - 14) * Math.cos(a)} y1={cy - (R - 14) * Math.sin(a)} x2={cx + (R - 9) * Math.cos(a)} y2={cy - (R - 9) * Math.sin(a)} stroke="#111111" strokeWidth="2" />;
        })}
        <line x1={cx} y1={cy} x2={nx} y2={ny} stroke="#111111" strokeWidth="4" strokeLinecap="round" />
        <circle cx={cx} cy={cy} r="8" fill="#111111" />
        <circle cx={nx} cy={ny} r="11" fill="#ffffff" stroke="#111111" strokeWidth="3" />
        <text x={cx - R - 2} y={cy + 18} fontSize="12" fill="#444" textAnchor="middle">{`${min}°`}</text>
        <text x={cx + R + 2} y={cy + 18} fontSize="12" fill="#444" textAnchor="middle">{`${max}°`}</text>
        <text x={cx} y={cy - 28} fontSize="30" fontWeight="800" textAnchor="middle" fill="#111111">
          {`${v.toFixed(step < 1 ? 1 : 0)} °C`}
        </text>
      </svg>
    </div>
  );
}

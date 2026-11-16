/* Two charts, drawn by hand: electricity day by day, and the indoor
 * temperature hour by hour. Black for what was measured, red for the model.
 */
import { useT } from "../i18n";

const W = 720;
const H = 220;
const PAD = 30;
const TOP = 34;

function shortDay(lang, iso) {
  const d = new Date(`${iso.slice(0, 10)}T12:00:00`);
  return d.toLocaleDateString(lang === "es" ? "es-ES" : "en-GB", { day: "numeric", month: "short" });
}

function Legend({ items }) {
  return (
    <div className="legend">
      {items.map(([colour, text]) => (
        <span key={text}>
          <i style={{ background: colour }} />
          {text}
        </span>
      ))}
    </div>
  );
}

export function DailyChart({ daily, title }) {
  const { t, n, lang } = useT();
  if (!daily?.length) return null;
  const max = Math.max(...daily.map((d) => Math.max(d.measured, d.twin)), 1);
  const bw = (W - 2 * PAD) / daily.length;
  const y = (v) => H - PAD - (v / max) * (H - PAD - TOP);
  return (
    <figure className="chart">
      <figcaption className="tile-label">{title}</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={title}>
        {daily.map((d, i) => (
          <rect
            key={d.day}
            x={PAD + i * bw + 1}
            y={y(d.measured)}
            width={Math.max(bw - 2, 1)}
            height={H - PAD - y(d.measured)}
            fill="#111111"
          />
        ))}
        <polyline
          points={daily.map((d, i) => `${PAD + (i + 0.5) * bw},${y(d.twin)}`).join(" ")}
          fill="none"
          stroke="#e2231a"
          strokeWidth="3"
        />
        <line x1={PAD} x2={W - PAD} y1={H - PAD} y2={H - PAD} stroke="#111111" strokeWidth="2" />
        <text x={PAD} y={TOP - 10} fontSize="13" fill="#111111">
          {t("kwh_a_day", { kwh: n(max) })}
        </text>
        <text x={PAD} y={H - 8} fontSize="13" fill="#111111">
          {shortDay(lang, daily[0].day)}
        </text>
        <text x={W - PAD} y={H - 8} fontSize="13" fill="#111111" textAnchor="end">
          {shortDay(lang, daily[daily.length - 1].day)}
        </text>
      </svg>
      <Legend items={[["#111111", t("your_meter")], ["#e2231a", t("your_model")]]} />
    </figure>
  );
}

export function IndoorChart({ points, title }) {
  const { t, lang } = useT();
  if (!points?.length) return null;
  const values = points.flatMap((p) => [p.measured, p.twin]).filter((v) => v != null);
  const lo = Math.floor(Math.min(...values)) - 1;
  const hi = Math.ceil(Math.max(...values)) + 1;
  const x = (i) => PAD + (i / Math.max(points.length - 1, 1)) * (W - 2 * PAD);
  const y = (v) => H - PAD - ((v - lo) / (hi - lo)) * (H - PAD - TOP);
  const line = (key) =>
    points
      .map((p, i) => (p[key] == null ? null : `${x(i)},${y(p[key])}`))
      .filter(Boolean)
      .join(" ");
  return (
    <figure className="chart" data-chart="indoor">
      <figcaption className="tile-label">{title}</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={title}>
        {points.map((p, i) =>
          i % 24 === 0 ? (
            <line key={i} x1={x(i)} x2={x(i)} y1={TOP} y2={H - PAD} stroke="#dddddd" strokeWidth="1" />
          ) : null,
        )}
        <polyline points={line("measured")} fill="none" stroke="#111111" strokeWidth="3" />
        <polyline points={line("twin")} fill="none" stroke="#e2231a" strokeWidth="2" />
        <text x={PAD} y={TOP - 10} fontSize="13" fill="#111111">{`${hi} °C`}</text>
        <text x={PAD} y={H - PAD + 16} fontSize="13" fill="#111111">{`${lo} °C`}</text>
        <text x={PAD + 46} y={H - 8} fontSize="13" fill="#111111">
          {shortDay(lang, points[0].time)}
        </text>
        <text x={W - PAD} y={H - 8} fontSize="13" fill="#111111" textAnchor="end">
          {shortDay(lang, points[points.length - 1].time)}
        </text>
      </svg>
      <Legend items={[["#111111", t("your_thermometer")], ["#e2231a", t("your_model")]]} />
    </figure>
  );
}

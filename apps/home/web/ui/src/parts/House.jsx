/* The house, drawn: what comes in, what conditioning the rooms costs, and
 * the month's bill beside it.
 *
 * One SVG, no library, and as little text as the numbers allow: the fuel
 * is a pictogram on a disc (bolt, flame, drop), the month and the outdoor
 * temperature stand outside the house, the indoor temperature inside it.
 * Inside: the machine with its nameplate power, the energy spent on
 * heating (or cooling) with an info button for the detail (heat delivered,
 * other heat, losses), and one bar per fuel of where that fuel goes, its
 * uses listed under it. Beside the house, the monthly bill: electricity,
 * gas (when there is any) and water, each marked when it is estimated.
 */
import { useState } from "react";

import { useT } from "../i18n";
import { BAND_COLOUR } from "./bits";

const W = 880;
const BLACK = "#111111";
const BLUE = "#005bbb";
const RED = "#e2231a";
const YELLOW = "#ffc72c";
const GREY = "#9a9a95";
const FUEL_COLOUR = { electricity: BLUE, gas: RED, water: BLACK };
const USE_COLOUR = {
  heating: RED,
  cooling: "#7fb3e6",
  "hot water": BLUE,
  cooking: YELLOW,
  appliances: BLACK,
  always_on: GREY,
};

/* ---------------------------------------------------------- pictograms
 * Each is drawn around (0, 0), white on its disc; `s` scales it. */
function Bolt({ s = 1 }) {
  return <polygon points="3,-16 -9,2 -1,2 -4,16 9,-3 1,-3" fill="#ffffff" transform={`scale(${s})`} />;
}
function Flame({ s = 1 }) {
  return (
    <path
      d="M0,-16 C5,-9 11,-5 11,4 A11,11 0 0 1 -11,4 C-11,-2 -6,-6 -4,-11 C-3,-7 -1,-5 1,-4 C3,-7 3,-11 0,-16 Z"
      fill="#ffffff"
      transform={`scale(${s})`}
    />
  );
}
function Drop({ s = 1 }) {
  return <path d="M0,-16 C5,-8 11,-2 11,5 A11,11 0 0 1 -11,5 C-11,-2 -5,-8 0,-16 Z" fill="#ffffff" transform={`scale(${s})`} />;
}
const FUEL_GLYPH = { electricity: Bolt, gas: Flame, water: Drop };
function Fan() {
  return (
    <g stroke="#ffffff" fill="#ffffff">
      <circle r="15" fill="none" strokeWidth="3" />
      <circle r="3.5" stroke="none" />
      {[90, 210, 330].map((deg) => (
        <line key={deg} x1="0" y1="-4" x2="0" y2="-11" strokeWidth="4" strokeLinecap="round" transform={`rotate(${deg})`} />
      ))}
    </g>
  );
}
function Coil() {
  return <polyline points="-14,0 -10,-9 -5,9 0,-9 5,9 10,-9 14,0" fill="none" stroke="#ffffff" strokeWidth="3.5" strokeLinejoin="round" />;
}
/* a thermometer: bulb and stem */
function Thermo({ c = BLACK }) {
  return (
    <g fill={c}>
      <rect x="-3" y="-16" width="6" height="20" rx="3" />
      <circle cy="9" r="5.5" />
      <rect x="-1" y="-10" width="2" height="14" fill="#ffffff" />
    </g>
  );
}
/* the uses, 14-unit glyphs */
function Radiator({ c }) {
  return (
    <g fill={c}>
      {[-6, -2, 2, 6].map((x) => (
        <rect key={x} x={x - 1.5} y={-7} width="3" height="14" />
      ))}
    </g>
  );
}
function Tap({ c }) {
  return (
    <g fill={c}>
      <rect x="-7" y="-7" width="10" height="3" />
      <rect x="-3" y="-7" width="3" height="7" />
      <rect x="-7" y="-1" width="11" height="3" />
      <path d="M5,3 C7,6 8,7 8,9 A3,3 0 0 1 2,9 C2,7 3,6 5,3 Z" />
    </g>
  );
}
function Pot({ c }) {
  return (
    <g fill={c}>
      <rect x="-7" y="-2" width="14" height="9" />
      <rect x="-9" y="-4" width="18" height="2" />
      <rect x="-1" y="-7" width="2" height="3" />
    </g>
  );
}
function Plug({ c }) {
  return (
    <g fill={c}>
      <rect x="-6" y="-2" width="12" height="9" />
      <rect x="-4" y="-7" width="2.5" height="5" />
      <rect x="1.5" y="-7" width="2.5" height="5" />
    </g>
  );
}
function Clock({ c }) {
  return (
    <g>
      <circle r="7" fill="none" stroke={c} strokeWidth="2" />
      <polyline points="0,-4 0,0 3,2" fill="none" stroke={c} strokeWidth="2" />
    </g>
  );
}
function Snow({ c }) {
  return (
    <g stroke={c} strokeWidth="2">
      <line x1="0" y1="-7" x2="0" y2="7" />
      <line x1="-6" y1="-3.5" x2="6" y2="3.5" />
      <line x1="-6" y1="3.5" x2="6" y2="-3.5" />
    </g>
  );
}
const USE_GLYPH = { heating: Radiator, "hot water": Tap, cooking: Pot, appliances: Plug, always_on: Clock, cooling: Snow };

/* --------------------------------------------------------------- pieces */
function Arrow({ x1, x2, y, colour, width = 4, dashed = false }) {
  const head = 7 + width;
  const base = x2 - head;
  return (
    <g>
      <line x1={x1} x2={base} y1={y} y2={y} stroke={colour} strokeWidth={width} strokeDasharray={dashed ? "6 5" : undefined} />
      <polygon points={`${x2},${y} ${base},${y - head * 0.7} ${base},${y + head * 0.7}`} fill={colour} />
    </g>
  );
}

function Disc({ x, y, r = 27, colour, children }) {
  return (
    <g transform={`translate(${x} ${y})`}>
      <circle r={r} fill={colour} />
      {children}
    </g>
  );
}

function Input({ y, fuel, value, used }) {
  const Glyph = FUEL_GLYPH[fuel];
  const colour = used ? FUEL_COLOUR[fuel] : GREY;
  return (
    <g data-flow={fuel}>
      <Disc x={64} y={y} colour={colour}>
        <Glyph />
      </Disc>
      <text x={104} y={y + 6} fontSize="17" fontWeight="700" fill={used ? BLACK : "#777"}>
        {value}
      </text>
      <Arrow x1={214} x2={296} y={y} colour={colour} dashed={!used} />
    </g>
  );
}

/* one fuel's bar and, under it, its uses */
function FuelBar({ fuel, rows, y, kwh }) {
  const total = rows.reduce((s, r) => s + r.kwh, 0) || 1;
  const Glyph = FUEL_GLYPH[fuel];
  let acc = 0;
  const x0 = 350;
  const width = 228;
  return (
    <g data-bar={fuel}>
      <Disc x={332} y={y + 8} r={9} colour={FUEL_COLOUR[fuel]}>
        <Glyph s={0.5} />
      </Disc>
      <rect x={x0} y={y} width={width} height="16" fill="none" stroke={BLACK} strokeWidth="1" />
      {rows.map((r) => {
        const x = x0 + (acc / total) * width;
        acc += r.kwh;
        return <rect key={r.use} x={x} y={y} width={Math.max((r.kwh / total) * width, 0)} height="16" fill={USE_COLOUR[r.use] || GREY} />;
      })}
      {rows.map((r, i) => {
        const Use = USE_GLYPH[r.use] || Plug;
        const x = 332 + (i % 2) * 126;
        const yy = y + 36 + Math.floor(i / 2) * 26;
        return (
          <g key={r.use} data-use={r.use}>
            <rect x={x} y={yy - 8} width="16" height="16" fill={USE_COLOUR[r.use] || GREY} />
            <g transform={`translate(${x + 8} ${yy})`}>
              <Use c={r.use === "cooking" ? BLACK : "#ffffff"} />
            </g>
            <text x={x + 22} y={yy - 1} fontSize="11" fontWeight="700" fill={BLACK}>
              {r.label}
            </text>
            <text x={x + 22} y={yy + 11} fontSize="11" fill="#444">
              {kwh(r.kwh)}
            </text>
          </g>
        );
      })}
    </g>
  );
}

/* ------------------------------------------------------------- the house */
export function House({ flows, band, caption }) {
  const { t, n } = useT();
  const [info, setInfo] = useState(false);
  if (!flows) return null;
  const stroke = BAND_COLOUR[band] || GREY;
  const kwh = (v) => t("kwh", { kwh: n(v) });
  const eur = (v) => t("eur", { eur: n(v) });
  const period = flows.period || {};
  const bill = flows.bill || {};
  const machine =
    flows.heater === "gas" ? ["gas", RED, Flame] : flows.heater === "heat_pump" ? ["heat_pump", BLUE, Fan] : flows.heater === "electric" ? ["electric", BLUE, Coil] : null;
  const Machine = machine ? machine[2] : null;
  const conditioning = flows.conditioning || [];
  const fuels = Object.entries(flows.by_fuel || {}).filter(([, rows]) => rows.some((r) => r.kwh > 0.5));
  const hasGas = flows.gas_kwh > 0;

  // the layout grows with the bars inside the house
  let y = 256;
  const bars = fuels.map(([fuel, rows]) => {
    const block = { fuel, rows: rows.filter((r) => r.kwh > 0.5), y };
    y += 36 + Math.ceil(block.rows.length / 2) * 26 + 10;
    return block;
  });
  const bottom = Math.max(405, y + 8);
  const H = bottom + 72;
  const billRows = [
    ["electricity", bill.electricity, bill.electricity ? kwh(bill.electricity.kwh) : ""],
    ...(bill.gas ? [["gas", bill.gas, kwh(bill.gas.kwh)]] : []),
    ["water", bill.water, bill.water ? t("m3", { m3: n(bill.water.m3, 1) }) : ""],
  ].filter(([, part]) => part);
  const billHeight = 52 + billRows.length * 48 + 44;

  return (
    <figure className="house" data-band={band}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={t("house_title")}>
        {/* outside, top left: the month and the outdoor temperature */}
        <g data-flow="outdoor">
          <text x="40" y="78" fontSize="22" fontWeight="800" letterSpacing="1" fill={BLACK}>
            {String(period.label || "").toUpperCase()}
          </text>
          {period.periods > 1 ? (
            <text x="40" y="96" fontSize="11" fill="#444">
              {t("avg_of", { n: period.periods })}
            </text>
          ) : null}
          <g transform="translate(48 128)">
            <Thermo />
          </g>
          <text x="64" y="134" fontSize="18" fontWeight="700" fill={BLACK}>
            {period.outdoor_c != null ? `${n(period.outdoor_c, 1)} °C` : ""}
          </text>
        </g>

        {/* the inputs */}
        <Input y={200} fuel="electricity" value={kwh(flows.electricity_kwh)} used={flows.electricity_kwh > 0} />
        <Input y={275} fuel="gas" value={hasGas ? kwh(flows.gas_kwh) : "—"} used={hasGas} />
        <Input y={350} fuel="water" value={t("m3", { m3: n(flows.water_m3, 1) })} used />

        {/* the house: a square and a triangle, its border the traffic light */}
        <rect x="300" y="150" width="300" height={bottom - 150} rx="14" fill="#ffffff" stroke={stroke} strokeWidth="10" />
        <path d="M292,150 L450,52 L608,150" fill="#ffffff" stroke={stroke} strokeWidth="10" strokeLinejoin="round" strokeLinecap="round" />

        {/* inside, under the roof: the indoor temperature */}
        <g data-flow="indoor">
          <g transform="translate(426 126)">
            <Thermo />
          </g>
          <text x="440" y="132" fontSize="15" fontWeight="700" fill={BLACK}>
            {period.indoor_c != null ? `${n(period.indoor_c, 1)} °C` : ""}
          </text>
        </g>

        {/* inside: the machine and what conditioning the rooms cost */}
        {machine ? (
          <g data-machine={machine[0]}>
            <rect x="322" y="176" width="54" height="54" fill={machine[1]} />
            <g transform="translate(349 203)">
              <Machine />
            </g>
            <text x="390" y="188" fontSize="12" fontWeight="800" letterSpacing="1" fill={BLACK}>
              {t(`machine_${machine[0]}`).toUpperCase()}
              {flows.heater_kw ? (
                <tspan fontWeight="700" letterSpacing="0" fill="#444">{` · ${t("kw", { kw: n(flows.heater_kw, 1) })}`}</tspan>
              ) : null}
            </text>
          </g>
        ) : (
          <text x="322" y="188" fontSize="12" fontWeight="800" letterSpacing="1" fill={BLACK}>
            {t("machine_none").toUpperCase()}
          </text>
        )}
        <g data-flow="conditioning">
          {conditioning.length ? (
            conditioning.map((c, i) => {
              const Glyph = FUEL_GLYPH[c.fuel];
              const yy = 218 + i * 22;
              return (
                <g key={c.kind}>
                  <Disc x={399} y={yy - 6} r={9} colour={FUEL_COLOUR[c.fuel]}>
                    <Glyph s={0.5} />
                  </Disc>
                  <text x={414} y={yy} fontSize={conditioning.length > 1 ? 15 : 20} fontWeight="800" fill={BLACK}>
                    {kwh(c.kwh)}
                  </text>
                  {conditioning.length > 1 ? (
                    <g transform={`translate(${520} ${yy - 5})`}>{c.kind === "cooling" ? <Snow c={BLACK} /> : <Radiator c={BLACK} />}</g>
                  ) : null}
                </g>
              );
            })
          ) : (
            <text x="414" y="218" fontSize="20" fontWeight="800" fill={BLACK}>
              —
            </text>
          )}
          {/* the info button: the detail behind the number */}
          <g
            className="info"
            role="button"
            tabIndex={0}
            aria-label={t("details")}
            onClick={() => setInfo((v) => !v)}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && setInfo((v) => !v)}
            transform="translate(570 212)"
            style={{ cursor: "pointer" }}
          >
            <circle r="10" fill={info ? BLACK : "#ffffff"} stroke={BLACK} strokeWidth="2" />
            <text y="4" fontSize="13" fontWeight="800" textAnchor="middle" fill={info ? "#ffffff" : BLACK} fontFamily="Georgia, serif" fontStyle="italic">
              i
            </text>
          </g>
        </g>

        {/* inside: one bar per fuel, its uses under it */}
        {bars.map((b) => (
          <FuelBar key={b.fuel} fuel={b.fuel} rows={b.rows} y={b.y} kwh={kwh} />
        ))}

        {/* beside the house: the monthly bill */}
        <g data-flow="bill">
          <rect x="640" y="52" width="210" height={billHeight} fill="#ffffff" stroke={BLACK} strokeWidth="3" />
          <rect x="640" y="52" width="210" height="4" fill={BLACK} />
          <text x="656" y="80" fontSize="12" fontWeight="800" letterSpacing="1" fill={BLACK}>
            {t("monthly_bill").toUpperCase()}
          </text>
          {billRows.map(([fuel, part, amount], i) => {
            const Glyph = FUEL_GLYPH[fuel];
            const yy = 110 + i * 48;
            return (
              <g key={fuel} data-bill={fuel}>
                <Disc x={668} y={yy} r={12} colour={FUEL_COLOUR[fuel]}>
                  <Glyph s={0.6} />
                </Disc>
                <text x={690} y={yy + 1} fontSize="18" fontWeight="800" fill={BLACK}>
                  {eur(part.eur)}
                </text>
                <text x={690} y={yy + 17} fontSize="11" fill="#444">
                  {amount}
                  {part.exact ? "" : ` · ${t("estimated")}`}
                </text>
              </g>
            );
          })}
          <line x1="656" x2="834" y1={52 + billHeight - 42} y2={52 + billHeight - 42} stroke={BLACK} strokeWidth="2" />
          <text x="656" y={52 + billHeight - 16} fontSize="11" fontWeight="800" letterSpacing="1" fill={BLACK}>
            {t("bill_total").toUpperCase()}
          </text>
          <text x="834" y={52 + billHeight - 14} fontSize="20" fontWeight="800" textAnchor="end" fill={BLACK}>
            {eur(bill.total_eur || 0)}
          </text>
        </g>

        {/* the ground */}
        <line x1="20" x2={W - 20} y1={bottom + 15} y2={bottom + 15} stroke={BLACK} strokeWidth="3" />
        <text x="20" y={bottom + 40} fontSize="12" fill="#444">
          {caption}
        </text>
      </svg>
      {info ? (
        <div className="house-info" data-info="open">
          <p className="tile-label">{t("details")}</p>
          <dl className="summary">
            {[
              ["detail_heat_made", flows.heat_kwh != null ? kwh(flows.heat_kwh) : "—"],
              ["detail_other_heat", kwh(flows.gains_kwh || 0)],
              ["detail_loss_rate", `${t("w_per_k", { w: n(flows.loss_w_per_k) })} · ${t("kw", { kw: n(flows.loss_kw, 1) })}`],
              ["detail_loss", kwh(flows.loss_kwh)],
              ["detail_fabric", kwh(flows.loss_fabric_kwh)],
              ["detail_radiation", kwh(flows.loss_radiation_kwh || 0)],
              ["detail_air", kwh(flows.loss_air_kwh)],
            ].map(([k, v]) => (
              <div key={k} style={{ display: "contents" }}>
                <dt>{t(k)}</dt>
                <dd>{v}</dd>
              </div>
            ))}
          </dl>
          <p className="small">{t("detail_note")}</p>
        </div>
      ) : null}
    </figure>
  );
}

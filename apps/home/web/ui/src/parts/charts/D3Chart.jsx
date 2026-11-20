/* One chart for every curve the page draws, built with D3.
 *
 * Series share one time axis. Each is a line (the twin, in blue, and
 * whatever is compared with it), points (what was measured, in black) or
 * a band (the twin's uncertainty: blue, translucent, strongest at the
 * centre and fading to 10 % at its edges). Real axes with real values and
 * units, grid lines, a legend that focuses one series when clicked, a
 * crosshair with the values under the pointer, and zoom on the time axis
 * with the wheel or a drag (double-click to reset).
 *
 *   <D3Chart
 *     series={[{ id, name, colour, kind: "line" | "points" | "step", points: [{ x: Date, y }], band: [{ x, lo, hi }] }]}
 *     unit="kWh" yLabel="kWh a day" height={320} monthly
 *   />
 */
import * as d3 from "d3";
import { useEffect, useId, useRef, useState } from "react";

import { useT } from "../../i18n";

export const TWIN_BLUE = "#005bbb";
export const MEASURED_BLACK = "#111111";
export const SCENARIO_COLOURS = ["#e2231a", "#d9a300", "#5c5c57"];

const MARGIN = { top: 18, right: 22, bottom: 42, left: 62 };

export function D3Chart({ series, unit = "", yLabel = "", height = 320, monthly = false, caption, bandLabel }) {
  const { lang, t } = useT();
  const ref = useRef(null);
  const wrap = useRef(null);
  const gid = useId().replace(/:/g, "");
  const [focus, setFocus] = useState(null);
  const [width, setWidth] = useState(760);

  useEffect(() => {
    if (!wrap.current) return undefined;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect?.width;
      if (w && Math.abs(w - width) > 2) setWidth(Math.max(320, Math.floor(w)));
    });
    ro.observe(wrap.current);
    return () => ro.disconnect();
  }, [width]);

  useEffect(() => {
    const svgEl = ref.current;
    if (!svgEl || !series?.length) return undefined;
    const svg = d3.select(svgEl);
    svg.selectAll("*").remove();
    const w = width - MARGIN.left - MARGIN.right;
    const h = height - MARGIN.top - MARGIN.bottom;
    const locale = lang === "es" ? d3.timeFormatLocale(ES_LOCALE) : d3.timeFormatLocale(EN_LOCALE);
    const numberLocale = d3.formatLocale(lang === "es" ? { decimal: ",", thousands: ".", grouping: [3], currency: ["", " €"] } : { decimal: ".", thousands: ",", grouping: [3], currency: ["", " €"] });

    const allX = series.flatMap((s) => [...(s.points || []).map((p) => p.x), ...(s.band || []).map((p) => p.x)]);
    const allY = series.flatMap((s) => [...(s.points || []).map((p) => p.y), ...(s.band || []).flatMap((p) => [p.lo, p.hi])]).filter((v) => v != null && Number.isFinite(v));
    const x0 = d3.scaleTime().domain(d3.extent(allX)).range([0, w]);
    if (monthly) {
      const [a, b] = x0.domain();
      x0.domain([d3.timeMonth.offset(a, 0) - 14 * 86400e3, d3.timeMonth.offset(b, 0).getTime() + 14 * 86400e3]);
    }
    const yMax = d3.max(allY) || 1;
    const yMin = Math.min(0, d3.min(allY) || 0);
    const y = d3.scaleLinear().domain([yMin, yMax * 1.08]).nice().range([h, 0]);

    const defs = svg.append("defs");
    defs.append("clipPath").attr("id", `clip-${gid}`).append("rect").attr("width", w).attr("height", h);
    // the band's gradient: strongest at the centre, 10 % at the edges
    series.forEach((s, i) => {
      const g = defs.append("linearGradient").attr("id", `band-${gid}-${i}`).attr("x1", "0").attr("x2", "0").attr("y1", "0").attr("y2", "1");
      g.append("stop").attr("offset", "0%").attr("stop-color", s.colour).attr("stop-opacity", 0.1);
      g.append("stop").attr("offset", "50%").attr("stop-color", s.colour).attr("stop-opacity", 0.4);
      g.append("stop").attr("offset", "100%").attr("stop-color", s.colour).attr("stop-opacity", 0.1);
    });

    const root = svg.append("g").attr("transform", `translate(${MARGIN.left},${MARGIN.top})`);
    const grid = root.append("g").attr("class", "grid");
    const plot = root.append("g").attr("clip-path", `url(#clip-${gid})`);
    const xAxisG = root.append("g").attr("class", "axis x").attr("transform", `translate(0,${h})`);
    const yAxisG = root.append("g").attr("class", "axis y");

    const fmtY = (v) => (unit === "€" ? numberLocale.format("$,.0f")(v) : `${numberLocale.format(",.0f")(v)}${unit ? ` ${unit}` : ""}`);
    const yAxis = d3.axisLeft(y).ticks(6).tickFormat(fmtY).tickSize(-4).tickPadding(8);
    const timeFormat = (date) => {
      if (monthly) return locale.format("%b")(date);
      const span = x0.domain()[1] - x0.domain()[0];
      return span > 120 * 86400e3 ? locale.format("%b %Y")(date) : span > 10 * 86400e3 ? locale.format("%-d %b")(date) : locale.format("%-d %b %H:%M")(date);
    };

    const draw = (x) => {
      const xAxis = d3.axisBottom(x).tickFormat(timeFormat).tickSize(6).tickPadding(8);
      if (monthly) xAxis.tickValues((series[0].points || []).map((p) => p.x));
      else xAxis.ticks(Math.min(10, Math.floor(w / 80)));
      xAxisG.call(xAxis);
      yAxisG.call(yAxis);
      grid.selectAll("*").remove();
      grid.selectAll("line.h").data(y.ticks(6)).join("line").attr("class", "h").attr("x1", 0).attr("x2", w).attr("y1", (v) => y(v)).attr("y2", (v) => y(v));
      plot.selectAll("*").remove();
      const dim = (s) => (focus && focus !== s.id ? 0.18 : 1);
      // bands first, under the lines
      series.forEach((s, i) => {
        if (!s.band?.length) return;
        const area = d3
          .area()
          .x((p) => x(p.x))
          .y0((p) => y(p.lo))
          .y1((p) => y(p.hi))
          .curve(monthly ? d3.curveMonotoneX : d3.curveLinear);
        plot.append("path").datum(s.band).attr("class", "band").attr("data-series", s.id).attr("fill", `url(#band-${gid}-${i})`).attr("opacity", dim(s) * (s.id === focus || !focus || s.primary ? 1 : 0.5)).attr("d", area);
      });
      series.forEach((s) => {
        const pts = (s.points || []).filter((p) => p.y != null && Number.isFinite(p.y));
        if (!pts.length) return;
        if (s.kind === "points") {
          plot
            .selectAll(`circle.s-${s.id}`)
            .data(pts)
            .join("circle")
            .attr("class", `series points s-${s.id}`)
            .attr("data-series", s.id)
            .attr("cx", (p) => x(p.x))
            .attr("cy", (p) => y(p.y))
            .attr("r", 3.2)
            .attr("fill", s.colour)
            .attr("opacity", dim(s));
          const thin = d3.line().x((p) => x(p.x)).y((p) => y(p.y)).curve(d3.curveStepAfter);
          plot.append("path").datum(pts).attr("class", "series thin").attr("data-series", s.id).attr("fill", "none").attr("stroke", s.colour).attr("stroke-width", 1).attr("opacity", dim(s) * 0.6).attr("d", thin);
        } else {
          const line = d3
            .line()
            .x((p) => x(p.x))
            .y((p) => y(p.y))
            .curve(s.kind === "step" ? d3.curveStepAfter : monthly ? d3.curveMonotoneX : d3.curveLinear);
          plot.append("path").datum(pts).attr("class", `series line s-${s.id}`).attr("data-series", s.id).attr("fill", "none").attr("stroke", s.colour).attr("stroke-width", s.primary ? 3 : 2.2).attr("opacity", dim(s)).attr("d", line);
          if (monthly) {
            plot.selectAll(`circle.m-${s.id}`).data(pts).join("circle").attr("class", `marker m-${s.id}`).attr("cx", (p) => x(p.x)).attr("cy", (p) => y(p.y)).attr("r", 3.5).attr("fill", s.colour).attr("opacity", dim(s));
          }
        }
      });
    };
    draw(x0);

    // the crosshair and the values under the pointer
    const hover = root.append("g").attr("class", "hover").style("display", "none");
    hover.append("line").attr("y1", 0).attr("y2", h);
    const tip = d3.select(wrap.current).select(".d3-tip");
    let current = x0;
    const bisect = d3.bisector((p) => p.x).center;
    svg
      .on("pointermove", (event) => {
        const [mx] = d3.pointer(event, root.node());
        if (mx < 0 || mx > w) return;
        const date = current.invert(mx);
        const rows = series
          .map((s) => {
            const pts = (s.points || []).filter((p) => p.y != null);
            if (!pts.length) return null;
            const p = pts[bisect(pts, date)];
            const b = s.band?.length ? s.band[bisect(s.band, date)] : null;
            return { s, p, b };
          })
          .filter(Boolean);
        if (!rows.length) return;
        const at = rows[0].p.x;
        hover.style("display", null).select("line").attr("x1", current(at)).attr("x2", current(at));
        tip
          .style("display", "block")
          .style("left", `${Math.min(current(at) + MARGIN.left + 12, width - 230)}px`)
          .html(
            `<strong>${monthly ? locale.format("%B")(at) : locale.format("%-d %b %Y")(at)}</strong>` +
              rows
                .map(
                  ({ s, p, b }) =>
                    `<div><i style="background:${s.colour}"></i>${s.name}: <b>${fmtY(p.y)}</b>${b ? ` <span class="muted">(${fmtY(b.lo)} – ${fmtY(b.hi)})</span>` : ""}</div>`,
                )
                .join(""),
          );
      })
      .on("pointerleave", () => {
        hover.style("display", "none");
        tip.style("display", "none");
      });

    // zoom on time, wheel or drag; double-click resets
    const zoom = d3
      .zoom()
      .scaleExtent([1, 24])
      .translateExtent([
        [0, 0],
        [w, h],
      ])
      .extent([
        [0, 0],
        [w, h],
      ])
      .on("zoom", (event) => {
        current = event.transform.rescaleX(x0);
        draw(current);
      });
    svg.call(zoom).on("dblclick.zoom", () => svg.transition().duration(300).call(zoom.transform, d3.zoomIdentity));
    return undefined;
  }, [series, width, height, unit, monthly, lang, focus, gid]);

  return (
    <figure className="chart d3-chart" ref={wrap}>
      <div className="d3-head">
        {yLabel ? <span className="tile-label">{yLabel}</span> : null}
        <span className="small zoom-hint">{t("chart_zoom_hint")}</span>
      </div>
      <div style={{ position: "relative" }}>
        <svg ref={ref} width={width} height={height} role="img" aria-label={caption || yLabel} />
        <div className="d3-tip" style={{ display: "none" }} />
      </div>
      <div className="legend">
        {series.map((s) => (
          <button key={s.id} type="button" className={`plain legend-item ${focus && focus !== s.id ? "dim" : ""}`} data-legend={s.id} onClick={() => setFocus(focus === s.id ? null : s.id)}>
            <i style={{ background: s.colour, borderRadius: s.kind === "points" ? "50%" : 0 }} />
            {s.name}
          </button>
        ))}
        {bandLabel ? (
          <span className="legend-item">
            <i style={{ background: TWIN_BLUE, opacity: 0.3 }} />
            {bandLabel}
          </span>
        ) : null}
      </div>
      {caption ? <figcaption className="small">{caption}</figcaption> : null}
    </figure>
  );
}

const EN_LOCALE = {
  dateTime: "%x, %X",
  date: "%-d/%-m/%Y",
  time: "%H:%M:%S",
  periods: ["AM", "PM"],
  days: ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"],
  shortDays: ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
  months: ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
  shortMonths: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
};
const ES_LOCALE = {
  dateTime: "%A, %e de %B de %Y, %X",
  date: "%d/%m/%Y",
  time: "%H:%M:%S",
  periods: ["AM", "PM"],
  days: ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"],
  shortDays: ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"],
  months: ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"],
  shortMonths: ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"],
};

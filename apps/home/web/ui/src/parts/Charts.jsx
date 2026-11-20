/* The two charts of a fit, on D3: electricity day by day (what the meter
 * measured, in black; the twin, in blue, with its band), and the indoor
 * temperature hour by hour (the thermometer in black, the twin in blue).
 */
import { useMemo } from "react";

import { useT } from "../i18n";
import { D3Chart, MEASURED_BLACK, TWIN_BLUE } from "./charts/D3Chart";

const day = (iso) => new Date(`${iso.slice(0, 10)}T12:00:00`);

export function DailyChart({ daily, title }) {
  const { t } = useT();
  const series = useMemo(() => {
    if (!daily?.length) return [];
    const twin = { id: "twin", name: t("your_model"), colour: TWIN_BLUE, kind: "line", primary: true, points: daily.map((d) => ({ x: day(d.day), y: d.twin })) };
    if (daily[0].lo != null) twin.band = daily.map((d) => ({ x: day(d.day), lo: d.lo, hi: d.hi }));
    return [
      twin,
      { id: "meter", name: t("your_meter"), colour: MEASURED_BLACK, kind: "points", points: daily.map((d) => ({ x: day(d.day), y: d.measured })) },
    ];
  }, [daily, t]);
  if (!series.length) return null;
  return <D3Chart series={series} unit="kWh" yLabel={title} height={300} bandLabel={daily[0].lo != null ? t("band_label") : null} />;
}

export function IndoorChart({ points, title }) {
  const { t } = useT();
  const series = useMemo(() => {
    if (!points?.length) return [];
    const at = (p) => new Date(p.time.replace(" ", "T"));
    return [
      { id: "twin", name: t("your_model"), colour: TWIN_BLUE, kind: "line", primary: true, points: points.map((p) => ({ x: at(p), y: p.twin })) },
      { id: "thermo", name: t("your_thermometer"), colour: MEASURED_BLACK, kind: "line", points: points.map((p) => ({ x: at(p), y: p.measured })) },
    ];
  }, [points, t]);
  if (!series.length) return null;
  return <D3Chart series={series} unit="°C" yLabel={title} height={260} />;
}

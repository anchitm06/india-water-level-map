export type Season = "pre" | "post";
export const SEASONS: Season[] = ["pre", "post"];
export const SEASON_LABEL: Record<Season, string> = { pre: "Pre-monsoon", post: "Post-monsoon" };

export interface Levels {
  meta: { placeholder: boolean; source: string; unit: string };
  years: number[];
  // stations: how many stations were measured; mixed: 1 where no manual wells pin the level
  // (both absent in placeholder data)
  data: Record<string, DistrictSeries>;
}
export type DistrictSeries = Record<Season, (number | null)[]> & { stations?: Record<Season, number[]>; mixed?: Record<Season, number[]> };

// public/data/stations/<district id>.json, written by pipeline/aggregate.py
// name: India-WRIS station name; place/km: nearest named place (GeoNames), absent if none within 10 km
export interface Station {
  id: string; lat: number; lon: number; manual: boolean; name?: string; place?: string; km?: number;
  pre: Record<string, number>; post: Record<string, number>;
}

/** "Near Hampur" (with the distance when it is 0.5 km or more), or the coordinates. */
export const nearText = (st: Station) => !st.place ? `${st.lat.toFixed(3)}° N, ${st.lon.toFixed(3)}° E`
  : `Near ${st.place}${st.km != null && st.km >= 0.5 ? ` (${st.km} km)` : ""}`;
/** The WRIS station name if there is one, else where the well is. */
export const wellName = (st: Station) => st.name ?? (st.place ? `Near ${st.place}` : `Well at ${nearText(st)}`);

export const stationsText = (n: number | undefined) => n == null ? "" : ` (${n} station${n === 1 ? "" : "s"})`;

/** A colour token from style.css/tokens.css as an rgb() string. MapLibre and Chart.js parse colours
 * themselves and do not all read oklch(), so each token is painted once to a 1px canvas and read back. */
const tokenCache = new Map<string, string>();
const probe = document.createElement("canvas").getContext("2d", { willReadFrequently: true })!;
export function token(name: string): string {
  let rgb = tokenCache.get(name);
  if (!rgb) {
    probe.clearRect(0, 0, 1, 1);
    probe.fillStyle = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    probe.fillRect(0, 0, 1, 1);
    const [r, g, b] = probe.getImageData(0, 0, 1, 1).data;
    tokenCache.set(name, (rgb = `rgb(${r}, ${g}, ${b})`));
  }
  return rgb;
}

// Depth to water (m bgl) classes, sequential light -> dark; deeper is worse. Colours are --data-1..6 in style.css.
export const CLASSES: [number, string][] = [
  [2, "--data-1"], [5, "--data-2"], [10, "--data-3"], [20, "--data-4"], [40, "--data-5"], [Infinity, "--data-6"],
];
export const noData = () => token("--data-none");
export const colorFor = (v: number | null | undefined) => v == null ? noData() : token(CLASSES.find(([max]) => v < max)![1]);

/** Point radius for a line series: a reading with no neighbour on either side is drawn as a dot,
 * since a line alone would not show it; every other point stays unmarked. */
export const loneDot = (r = 3) => (ctx: any) => {
  const d = ctx.dataset.data as (number | null)[], i = ctx.dataIndex;
  return d[i] != null && d[i - 1] == null && d[i + 1] == null ? r : 0;
};

/** Chart.js styling from the theme: the pre-monsoon series takes the accent, post-monsoon the pale ink. */
export const seriesColor = (s: Season) => token(s === "pre" ? "--color-accent" : "--color-ink-2");
export function chartTheme(Chart: any) {
  Chart.defaults.color = token("--color-muted");
  Chart.defaults.borderColor = token("--color-rule");
  Chart.defaults.font.family = getComputedStyle(document.documentElement).getPropertyValue("--font-body").trim();
  Chart.defaults.font.size = 12;
  Chart.defaults.plugins.legend.labels.color = token("--color-ink-2");
  Chart.defaults.plugins.legend.labels.boxWidth = 16;
  Chart.defaults.plugins.legend.labels.boxHeight = 2;
  Chart.defaults.plugins.tooltip.backgroundColor = token("--color-paper-3");
  Chart.defaults.plugins.tooltip.titleColor = token("--color-ink");
  Chart.defaults.plugins.tooltip.bodyColor = token("--color-ink-2");
  Chart.defaults.plugins.tooltip.borderColor = token("--color-rule");
  Chart.defaults.plugins.tooltip.borderWidth = 1;
  Chart.defaults.plugins.tooltip.cornerRadius = 0;
}

export const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

/** [[west, south], [east, north]] of a GeoJSON geometry. */
export function bbox(geom: any): [[number, number], [number, number]] {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  const walk = (c: any) => {
    if (typeof c[0] === "number") { x0 = Math.min(x0, c[0]); y0 = Math.min(y0, c[1]); x1 = Math.max(x1, c[0]); y1 = Math.max(y1, c[1]); }
    else c.forEach(walk);
  };
  walk(geom.coordinates);
  return [[x0, y0], [x1, y1]];
}
export const base = import.meta.env.BASE_URL;

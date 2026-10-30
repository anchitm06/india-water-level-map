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

// Depth to water (m bgl) classes, sequential light -> dark; deeper is worse.
export const CLASSES: [number, string][] = [
  [2, "#e6f2f7"], [5, "#b3d7e6"], [10, "#7fb7d4"], [20, "#e8c26a"], [40, "#d2793a"], [Infinity, "#8c2d1b"],
];
export const NO_DATA = "#c9cdd2";
export const colorFor = (v: number | null | undefined) => v == null ? NO_DATA : CLASSES.find(([max]) => v < max)![1];

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

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
export interface Station { id: string; lat: number; lon: number; manual: boolean; pre: Record<string, number>; post: Record<string, number> }

export const stationsText = (n: number | undefined) => n == null ? "" : ` (${n} station${n === 1 ? "" : "s"})`;

// Depth to water (m bgl) classes, sequential light -> dark; deeper is worse.
export const CLASSES: [number, string][] = [
  [2, "#e6f2f7"], [5, "#b3d7e6"], [10, "#7fb7d4"], [20, "#e8c26a"], [40, "#d2793a"], [Infinity, "#8c2d1b"],
];
export const NO_DATA = "#c9cdd2";
export const colorFor = (v: number | null | undefined) => v == null ? NO_DATA : CLASSES.find(([max]) => v < max)![1];

export const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
export const base = import.meta.env.BASE_URL;

import type { DistrictSeries, Levels, Season } from "./shared";

/** Least-squares slope in m/year over the non-null points; positive = water table deepening. */
export function slope(years: number[], values: (number | null)[]): number | null {
  const pts = years.map((y, i) => [y, values[i]] as const).filter((p): p is readonly [number, number] => p[1] != null);
  if (pts.length < 3) return null;
  const mx = pts.reduce((a, p) => a + p[0], 0) / pts.length, my = pts.reduce((a, p) => a + p[1], 0) / pts.length;
  const sxx = pts.reduce((a, p) => a + (p[0] - mx) ** 2, 0);
  return sxx ? pts.reduce((a, p) => a + (p[0] - mx) * (p[1] - my), 0) / sxx : null;
}

const median = (xs: number[]) => {
  const s = [...xs].sort((a, b) => a - b), m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};

export interface DistrictStats {
  latest: { year: number; value: number } | null;
  trend: number | null; // m/year, whole record
  trend10: number | null; // m/year, last 10 years up to the selected year
  change10: { from: number; delta: number } | null; // selected year vs ~10 years earlier
  recharge: number | null; // median monsoon rise (pre - post of the same year), last 10 years
  extremes: { deepest: [number, number]; shallowest: [number, number] } | null;
  rank: { rank: number; of: number } | null; // 1 = deepest in the state for the selected year
}

export function districtStats(levels: Levels, series: DistrictSeries, state: string, stateOf: Record<string, string>,
                              season: Season, yearIdx: number): DistrictStats {
  const { years } = levels;
  const vals = series[season];
  const upto = vals.slice(0, yearIdx + 1);
  const lastIdx = upto.map((v, i) => (v == null ? -1 : i)).filter((i) => i >= 0).pop();
  const latest = lastIdx == null ? null : { year: years[lastIdx], value: vals[lastIdx]! };

  const lo = Math.max(0, yearIdx - 9);
  const trend10 = slope(years.slice(lo, yearIdx + 1), vals.slice(lo, yearIdx + 1));

  let change10: DistrictStats["change10"] = null;
  if (vals[yearIdx] != null) {
    // nearest available year 9-11 years before, preferring exactly 10
    for (const back of [10, 11, 9]) {
      const j = yearIdx - back;
      if (j >= 0 && vals[j] != null) { change10 = { from: years[j], delta: vals[yearIdx]! - vals[j]! }; break; }
    }
  }

  const rises: number[] = [];
  for (let i = lo; i <= yearIdx; i++) {
    const pre = series.pre[i], post = series.post[i];
    if (pre != null && post != null) rises.push(pre - post);
  }

  const pts = years.map((y, i) => [y, vals[i]] as [number, number | null]).filter((p): p is [number, number] => p[1] != null);
  const extremes = pts.length ? {
    deepest: pts.reduce((a, p) => (p[1] > a[1] ? p : a)),
    shallowest: pts.reduce((a, p) => (p[1] < a[1] ? p : a)),
  } : null;

  let rank: DistrictStats["rank"] = null;
  const mine = vals[yearIdx];
  if (mine != null) {
    const peers = Object.entries(levels.data).filter(([id, s]) => stateOf[id] === state && s[season][yearIdx] != null);
    rank = { rank: 1 + peers.filter(([, s]) => s[season][yearIdx]! > mine).length, of: peers.length };
  }

  return { latest, trend: slope(years, vals), trend10, change10, recharge: rises.length ? median(rises) : null, extremes, rank };
}

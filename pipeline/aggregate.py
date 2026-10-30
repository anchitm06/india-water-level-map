"""Aggregate station readings to district x year x season water levels.

Inputs:
  pipeline/raw/readings.csv   station_id,lat,lon,date,level_m_bgl  (date is YYYY-MM-DD)
  public/data/districts.geojson  features with properties id, name, state
Output:
  public/data/levels.json  (same schema generate_placeholder.py writes, plus per district
  "stations": {pre: [...], post: [...]}, the number of stations measured that year, and
  "mixed": {pre: [...], post: [...]}, 1 where the level could not be pinned to manual wells)
  public/data/stations/<district id>.json  (per-station values for the detail view)

Seasons follow CGWB practice: pre-monsoon = Mar-May, post-monsoon = Oct-Dec.
Districts with no readings for a year/season get null, never an interpolated value.
District levels are chain-linked over stations measured in both years, not plain medians;
see district_series for why.

Each station is reduced to one value per (year, season) before the district median, so a
telemetric station with 90 daily readings counts the same as a manual well read once. Outliers
are removed per station, robustly (median and MAD, not mean and SD):
  1. daily spikes: a day far from the station's own median for that season (a sensor glitch);
  2. jumps: a season far from the same station's seasons within +-5 years (a drifting or
     mis-entered value, e.g. a batch of unrelated Delhi wells all at ~44 m in pre-monsoon 2017).
Both thresholds have a floor in metres so stable stations (MAD near 0) keep normal variation.
Comparing only nearby years lets long declines and recoveries through, and a season with too few
neighbours (e.g. 1994 followed by a gap to 2005) is kept rather than judged against distant years.
"""
import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEASON = {3: "pre", 4: "pre", 5: "pre", 10: "post", 11: "post", 12: "post"}
MAD_SCALE = 1.4826  # MAD -> standard deviation for normally distributed data
SPIKE_K, SPIKE_FLOOR_M = 5, 2.0  # daily readings vs the station's median for that season
JUMP_K, JUMP_FLOOR_M = 5, 15.0  # a station's season value vs its own nearby seasons
JUMP_WINDOW_Y = 5  # nearby = same station within this many years, so trends and recoveries pass
MIN_HISTORY = 3  # nearby seasons needed to judge; isolated seasons (data gaps) are kept
LINK_WINDOW_Y = 5  # district_series: how far back a year may look for shared stations
MIN_PAIRS = 3  # shared stations needed to trust a year-to-year link
MANUAL_MAX_DAYS = 3  # reading days in a season at or below which a station-season counts as manual
MANUAL_SHARE = 0.5  # share of a year's stations that must be manual for that year to pin a run


def far_from(ref: list[float], k: float, floor: float):
    """-> predicate: is a value more than max(k robust SDs, floor) metres from ref's median?"""
    med = statistics.median(ref)
    limit = max(k * MAD_SCALE * statistics.median(abs(v - med) for v in ref), floor)
    return lambda v: abs(v - med) > limit


def is_lat_lon_code(sid: str) -> bool:
    """CGWB-style 15-digit station code built from coordinates (283745077141501 = 28 37 45 N,
    77 14 15 E, well 01)."""
    return len(sid) == 15 and sid.isdigit()


def station_seasons(readings) -> tuple[dict[tuple[str, int, str], float], Counter, set]:
    """(station, YYYY-MM-DD, level) rows -> ({(station, year, season): level}, drop counts,
    manual station-season keys). Repeated (station, date) rows, which a fetch interrupted
    mid-window can leave, count once.

    A station-season is manual if it has at most MANUAL_MAX_DAYS reading days (manual wells are read
    once a season, telemetric ones daily) and the station has a CGWB-style lat/lon code. Checked
    Oct 2026: the ID alone is not enough (CGWB and West Bengal telemetric wells use lat/lon codes
    too), and frequency alone pulls in state networks (~6,000 Rajasthan state wells) that are
    deeper than CGWB's and made districts jump where runs were pinned to different networks.
    Judging per season handles a well that switched from manual to telemetric."""
    # Grouped straight into station-seasons, keyed by date inside, so the full file (8.5M rows in
    # Oct 2026) is never held as one flat list and repeated dates count once.
    by_season: dict[tuple[str, int, str], dict[str, float]] = defaultdict(dict)
    for sid, date, level in readings:
        season = SEASON.get(int(date[5:7]))
        if season and 0 < level < 200:  # fetch.clean_level applies the same bounds
            by_season[(sid, int(date[:4]), season)][sys.intern(date)] = level

    dropped: Counter = Counter()
    seasonal = {}
    manual = set()
    while by_season:
        key, days = by_season.popitem()
        if len(days) <= MANUAL_MAX_DAYS and is_lat_lon_code(key[0]):
            manual.add(key)
        levels = list(days.values())
        far = far_from(levels, SPIKE_K, SPIKE_FLOOR_M) if len(levels) >= 3 else (lambda v: False)
        bad = {i for i, v in enumerate(levels) if far(v)}
        if bad:
            dropped["daily spikes"] += len(bad)
        seasonal[key] = statistics.median(v for i, v in enumerate(levels) if i not in bad)

    history: dict[str, list[tuple]] = defaultdict(list)
    for key in seasonal:
        history[key[0]].append(key)
    jumps = []
    for keys in history.values():
        for key in keys:
            near = [seasonal[k] for k in keys if k != key and abs(k[1] - key[1]) <= JUMP_WINDOW_Y]
            if len(near) >= MIN_HISTORY and far_from(near, JUMP_K, JUMP_FLOOR_M)(seasonal[key]):
                jumps.append(key)
    for key in jumps:
        del seasonal[key]
        manual.discard(key)
    if jumps:
        dropped["station-season jumps"] = len(jumps)
    return seasonal, dropped, manual


def district_series(by_year: dict[int, dict[str, float]], years: list[int],
                    manual: dict[int, set[str]] | None = None) -> tuple[list, list]:
    """One district and season: {year: {station: level}} and {year: {manually read stations}}
    -> (levels, mixed) aligned with `years`.

    The set of measured wells changes over time (deep telemetric piezometers dominate from 2022),
    so a plain median per year tracks the well mix, not the water table. Instead:
      - trend: each year is linked to the latest earlier year within LINK_WINDOW_Y that shares at
        least MIN_PAIRS stations, by the median change of those shared stations (chain-linking);
      - level: each chained run is pinned to the median of manually read wells (mostly CGWB's
        national network, the one its yearbooks report) in the run's year with the most of them;
      - fallback: with no link the chain restarts. A run with no manual wells continues from the
        previous run's last level if that ended within LINK_WINDOW_Y, else it is pinned to its
        best-covered year's all-station median; both are flagged mixed (1). On the Oct 2026 data
        pinning such runs to their own median made 2015->2024 change 2.1 m in those districts vs
        0.3 m where manual wells pin the level."""
    runs: list[list[int]] = []
    rel: dict[int, float] = {}
    for y in sorted(by_year):
        link = None
        if runs:
            for back in reversed(runs[-1]):
                if y - back > LINK_WINDOW_Y:
                    break
                shared = by_year[y].keys() & by_year[back].keys()
                if len(shared) >= MIN_PAIRS:
                    link = (back, statistics.median(by_year[y][s] - by_year[back][s] for s in shared))
                    break
        if link:
            rel[y] = rel[link[0]] + link[1]
            runs[-1].append(y)
        else:
            rel[y] = 0.0
            runs.append([y])

    manual = manual or {}
    level: dict[int, float] = {}
    mixed: dict[int, int] = {}
    for n, run in enumerate(runs):
        hand = {y: [v for s, v in by_year[y].items() if s in manual.get(y, ())] for y in run}
        # A telemetric well that reported on only a few days looks manual. Three of them among 25
        # stations pinned Delhi 2023-26 at 2.1 m instead of ~8.5 m, so a year may pin the run only
        # if its manual wells are both MIN_PAIRS or more and at least MANUAL_SHARE of its stations.
        ok = [y for y in run if len(hand[y]) >= max(MIN_PAIRS, MANUAL_SHARE * len(by_year[y]))]
        flag = 0
        if ok:
            anchor = max(ok, key=lambda y: len(hand[y]))
            offset = statistics.median(hand[anchor]) - rel[anchor]
        elif n and run[0] - runs[n - 1][-1] <= LINK_WINDOW_Y:
            # No manual wells (typically a new telemetric network from 2020+) and nothing shared
            # with the run before: continue from that run's last level. That assumes no change over
            # the gap (tenths of a metre typically), far less wrong than pinning to deeper new wells.
            offset, flag = level[runs[n - 1][-1]] - rel[run[0]], 1
        else:
            anchor = max(run, key=lambda y: len(by_year[y]))
            offset, flag = statistics.median(by_year[anchor].values()) - rel[anchor], 1
        for y in run:
            level[y] = max(rel[y] + offset, 0.0)  # a chained run can't put water above ground on average
            mixed[y] = flag
    return ([round(level[y], 2) if y in level else None for y in years],
            [mixed.get(y, 0) for y in years])


def main() -> None:
    from shapely.geometry import Point, shape
    from shapely.strtree import STRtree

    gj = json.loads((ROOT / "public/data/districts.geojson").read_text(encoding="utf-8"))
    ids = [f["properties"]["id"] for f in gj["features"]]
    tree = STRtree([shape(f["geometry"]) for f in gj["features"]])

    pos: dict[str, tuple[float, float]] = {}
    n_rows = 0

    def readings():
        nonlocal n_rows
        with open(ROOT / "pipeline/raw/readings.csv", newline="", encoding="utf-8") as fh:
            for sid, lat, lon, date, level in csv.reader(fh):
                if sid == "station_id":  # header
                    continue
                sid = sys.intern(sid)
                if sid not in pos:
                    pos[sid] = (float(lon), float(lat))
                n_rows += 1
                yield sid, date, float(level)

    seasonal, dropped, manual = station_seasons(readings())

    district_of = {}
    for sid, xy in pos.items():
        hit = next(iter(tree.query(Point(xy), predicate="within")), None)
        district_of[sid] = None if hit is None else ids[hit]

    groups: dict[tuple[str, str], dict[int, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    hand: dict[tuple[str, str], dict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
    for (sid, year, season), level in seasonal.items():
        if district_of[sid] is not None:
            groups[(district_of[sid], season)][year][sid] = level
            if (sid, year, season) in manual:
                hand[(district_of[sid], season)][year].add(sid)

    years = sorted({y for g in groups.values() for y in g})
    data = {}
    for did in ids:
        d: dict = {"stations": {}, "mixed": {}}
        for s in ("pre", "post"):
            by_year = groups.get((did, s), {})
            d[s], d["mixed"][s] = district_series(by_year, years, hand.get((did, s)))
            d["stations"][s] = [len(by_year.get(y, ())) for y in years]
        data[did] = d
    (ROOT / "public/data/levels.json").write_text(json.dumps({
        "meta": {"placeholder": False, "source": "India-WRIS / CGWB", "unit": "m below ground level",
                 "method": "chain-linked on stations measured in both years, pinned to manually read wells"},
        "years": years, "data": data}, separators=(",", ":")), encoding="utf-8")
    n_files = write_station_files(seasonal, manual, district_of, pos)

    outside = sum(1 for d in district_of.values() if d is None)
    print(f"{n_rows} daily readings, {len(pos)} stations ({outside} outside every district), "
          f"{len(seasonal)} station-seasons kept; dropped {dict(dropped)}")
    print(f"{len(years)} years, {sum(1 for d in data.values() for s in ('pre', 'post') for x in d[s] if x is not None)} "
          f"district-season values -> public/data/levels.json; {n_files} station files -> public/data/stations/")


def write_station_files(seasonal: dict, manual: set, district_of: dict, pos: dict) -> int:
    """public/data/stations/<district id>.json: the district's cleaned station-season values, for the
    detail view's station map (loaded on demand; ~18 MB in total vs 387 MB of raw readings).
    Values are sparse, keyed by year: {"id", "lat", "lon", "manual", "pre": {"2015": 6.7}, "post": {...}};
    manual is true when most of the station's seasons were read by hand. With the GeoNames file
    present (see place_names.py) each station also gets "place" and "km", its nearest named place."""
    import place_names

    gazetteer = place_names.Gazetteer() if place_names.GEONAMES.exists() else None
    if gazetteer is None:
        print(f"no {place_names.GEONAMES}: wells get no place names (run pipeline/place_names.py)")
    by_district: dict[str, dict[str, dict]] = defaultdict(dict)
    hand_count: Counter = Counter()
    for (sid, year, season), level in seasonal.items():
        did = district_of.get(sid)
        if did is None:
            continue
        st = by_district[did].get(sid)
        if st is None:
            lon, lat = pos[sid]
            st = by_district[did][sid] = {"id": sid, "lat": lat, "lon": lon, "manual": False, "pre": {}, "post": {}}
        st[season][str(year)] = round(level, 2)
        hand_count[sid] += 1 if (sid, year, season) in manual else -1
    for stations in by_district.values():
        for sid, st in stations.items():
            st["manual"] = hand_count[sid] > 0
            near = gazetteer.nearest(st["lat"], st["lon"]) if gazetteer else None
            if near:
                st["place"], st["km"] = near[0], round(near[1], 1)
    out = ROOT / "public/data/stations"
    out.mkdir(exist_ok=True)
    for old in out.glob("*.json"):  # districts can lose all their stations between runs
        old.unlink()
    for did, stations in by_district.items():
        for st in stations.values():
            for s in ("pre", "post"):
                st[s] = dict(sorted(st[s].items()))
        (out / f"{did}.json").write_text(json.dumps({"stations": sorted(stations.values(), key=lambda s: s["id"])},
                                                    separators=(",", ":")), encoding="utf-8")
    return len(by_district)


if __name__ == "__main__":
    main()

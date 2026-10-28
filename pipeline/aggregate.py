"""Aggregate station readings to district x year x season medians.

Inputs:
  pipeline/raw/readings.csv   station_id,lat,lon,date,level_m_bgl  (date is YYYY-MM-DD)
  public/data/districts.geojson  features with properties id, name, state
Output:
  public/data/levels.json  (same schema generate_placeholder.py writes, plus per district
  "stations": {pre: [...], post: [...]}, the number of stations behind each median)

Seasons follow CGWB practice: pre-monsoon = Mar-May, post-monsoon = Oct-Dec.
Districts with no readings for a year/season get null, never an interpolated value.

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
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEASON = {3: "pre", 4: "pre", 5: "pre", 10: "post", 11: "post", 12: "post"}
MAD_SCALE = 1.4826  # MAD -> standard deviation for normally distributed data
SPIKE_K, SPIKE_FLOOR_M = 5, 2.0  # daily readings vs the station's median for that season
JUMP_K, JUMP_FLOOR_M = 5, 15.0  # a station's season value vs its own nearby seasons
JUMP_WINDOW_Y = 5  # nearby = same station within this many years, so trends and recoveries pass
MIN_HISTORY = 3  # nearby seasons needed to judge; isolated seasons (data gaps) are kept


def far_from(ref: list[float], k: float, floor: float):
    """-> predicate: is a value more than max(k robust SDs, floor) metres from ref's median?"""
    med = statistics.median(ref)
    limit = max(k * MAD_SCALE * statistics.median(abs(v - med) for v in ref), floor)
    return lambda v: abs(v - med) > limit


def station_seasons(readings) -> tuple[dict[tuple[str, int, str], float], Counter]:
    """(station, YYYY-MM-DD, level) rows -> ({(station, year, season): level}, drop counts).
    Repeated (station, date) rows, which a fetch interrupted mid-window can leave, count once."""
    daily: dict[tuple[str, str], float] = {}
    for sid, date, level in readings:
        if SEASON.get(int(date[5:7])) and 0 < level < 200:  # fetch.clean_level applies the same bounds
            daily[(sid, date)] = level
    groups: dict[tuple[str, int, str], list[float]] = defaultdict(list)
    for (sid, date), level in daily.items():
        groups[(sid, int(date[:4]), SEASON[int(date[5:7])])].append(level)

    dropped: Counter = Counter()
    seasonal = {}
    for key, levels in groups.items():
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
    if jumps:
        dropped["station-season jumps"] = len(jumps)
    return seasonal, dropped


def main() -> None:
    from shapely.geometry import Point, shape
    from shapely.strtree import STRtree

    gj = json.loads((ROOT / "public/data/districts.geojson").read_text(encoding="utf-8"))
    ids = [f["properties"]["id"] for f in gj["features"]]
    tree = STRtree([shape(f["geometry"]) for f in gj["features"]])

    pos: dict[str, tuple[float, float]] = {}
    with open(ROOT / "pipeline/raw/readings.csv", newline="", encoding="utf-8") as fh:
        rows = []
        for row in csv.DictReader(fh):
            pos.setdefault(row["station_id"], (float(row["lon"]), float(row["lat"])))
            rows.append((row["station_id"], row["date"], float(row["level_m_bgl"])))
    seasonal, dropped = station_seasons(rows)

    district_of = {}
    for sid, xy in pos.items():
        hit = next(iter(tree.query(Point(xy), predicate="within")), None)
        district_of[sid] = None if hit is None else ids[hit]

    buckets: dict[tuple[str, int, str], list[float]] = defaultdict(list)
    for (sid, year, season), level in seasonal.items():
        if district_of[sid] is not None:
            buckets[(district_of[sid], year, season)].append(level)

    years = sorted({y for _, y, _ in buckets})
    data = {}
    for did in ids:
        data[did] = {s: [round(statistics.median(v), 2) if (v := buckets.get((did, y, s))) else None for y in years]
                     for s in ("pre", "post")}
        data[did]["stations"] = {s: [len(buckets.get((did, y, s), ())) for y in years] for s in ("pre", "post")}
    (ROOT / "public/data/levels.json").write_text(json.dumps({
        "meta": {"placeholder": False, "source": "India-WRIS / CGWB", "unit": "m below ground level"},
        "years": years, "data": data}, separators=(",", ":")), encoding="utf-8")

    outside = sum(1 for d in district_of.values() if d is None)
    print(f"{len(rows)} daily readings, {len(pos)} stations ({outside} outside every district), "
          f"{len(seasonal)} station-seasons kept; dropped {dict(dropped)}")
    print(f"{len(years)} years, {sum(1 for d in data.values() for v in d.values() for x in v if x is not None)} "
          f"district-season values -> public/data/levels.json")


if __name__ == "__main__":
    main()

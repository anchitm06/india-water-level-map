"""Aggregate station readings to district x year x season medians.

Inputs:
  pipeline/raw/readings.csv   station_id,lat,lon,date,level_m_bgl  (date is YYYY-MM-DD)
  public/data/districts.geojson  features with properties id, name, state
Output:
  public/data/levels.json  (same schema generate_placeholder.py writes)

Seasons follow CGWB practice: pre-monsoon = Mar-May, post-monsoon = Oct-Dec.
Districts with no readings for a year/season get null, never an interpolated value.
"""
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path

from shapely.geometry import Point, shape
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parent.parent
SEASON = {3: "pre", 4: "pre", 5: "pre", 10: "post", 11: "post", 12: "post"}


def main() -> None:
    gj = json.loads((ROOT / "public/data/districts.geojson").read_text())
    ids = [f["properties"]["id"] for f in gj["features"]]
    polys = [shape(f["geometry"]) for f in gj["features"]]
    tree = STRtree(polys)

    buckets: dict[tuple[str, int, str], list[float]] = defaultdict(list)
    with open(ROOT / "pipeline/raw/readings.csv", newline="") as fh:
        for row in csv.DictReader(fh):
            season = SEASON.get(int(row["date"][5:7]))
            if season is None:
                continue
            pt = Point(float(row["lon"]), float(row["lat"]))
            hit = next((i for i in tree.query(pt, predicate="within")), None)
            if hit is None:
                continue
            level = float(row["level_m_bgl"])
            if 0 <= level < 200:  # drop obvious sensor/typing errors
                buckets[(ids[hit], int(row["date"][:4]), season)].append(level)

    years = sorted({y for _, y, _ in buckets})
    data = {}
    for did in ids:
        data[did] = {s: [round(statistics.median(v), 2) if (v := buckets.get((did, y, s))) else None for y in years]
                     for s in ("pre", "post")}
    (ROOT / "public/data/levels.json").write_text(json.dumps({
        "meta": {"placeholder": False, "source": "India-WRIS / CGWB", "unit": "m below ground level"},
        "years": years, "data": data}, separators=(",", ":")))


if __name__ == "__main__":
    main()

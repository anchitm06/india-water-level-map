"""Write SYNTHETIC placeholder data in the real schema.

The grid cells are not districts and the levels are random. This exists only so the
frontend can be built and tested while India-WRIS is unreachable. The real pipeline
(fetch.py -> aggregate.py) replaces both output files.
"""
import json
import math
import random
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "public" / "data"
YEARS = list(range(2000, 2025))
CELL = 1.0

# Very rough India outline (lon, lat), used only to pick which grid cells to keep.
OUTLINE = [(68.2, 23.5), (70, 20.5), (72.8, 19), (73.8, 15), (74.8, 12.5), (76.3, 9.5),
           (77.5, 8.1), (79.8, 10.3), (80.3, 15.5), (84.5, 19.5), (87, 21.5), (89, 22),
           (89, 26), (92.5, 25.5), (94, 24), (97.3, 27.8), (95, 29), (91.5, 28),
           (88.5, 27.5), (84, 28.8), (80.3, 30.5), (79, 33), (78, 35.5), (75, 37),
           (74, 34.5), (74.5, 32.5), (72, 30.5), (70.3, 28), (69.5, 26), (68.2, 23.5)]


def inside(x: float, y: float) -> bool:
    ok = False
    for (x1, y1), (x2, y2) in zip(OUTLINE, OUTLINE[1:] + OUTLINE[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            ok = not ok
    return ok


def from_districts(rng: random.Random) -> dict:
    """Random levels keyed to the real districts in districts.geojson (see build_districts.py)."""
    data = {}
    for f in json.loads((OUT / "districts.geojson").read_text())["features"]:
        ring = f["geometry"]["coordinates"]
        while isinstance(ring[0][0], list):
            ring = ring[0]
        lon, lat = ring[0]
        base = 3 + 12 * (1 + math.sin(lon / 6) * math.cos(lat / 5)) + rng.random() * 3
        drift = rng.uniform(-0.05, 0.25)
        pre, post = [], []
        for i, _ in enumerate(YEARS):
            p = base + drift * i + rng.gauss(0, 0.8)
            pre.append(round(max(p, 0.5), 2))
            post.append(round(max(p - 2.5 + rng.gauss(0, 0.5), 0.3), 2))
        data[f["properties"]["id"]] = {"pre": pre, "post": post}
    return data


def main() -> None:
    rng = random.Random(7)
    if "--keep-districts" in sys.argv:
        data = from_districts(rng)
        write_levels(data)
        print(f"wrote placeholder levels for {len(data)} real districts")
        return
    feats, data = [], {}
    n = 0
    lat = 8.0
    while lat < 37:
        lon = 68.0
        while lon < 98:
            if inside(lon + CELL / 2, lat + CELL / 2):
                n += 1
                did = f"PH{n:03d}"
                ring = [[lon, lat], [lon + CELL, lat], [lon + CELL, lat + CELL], [lon, lat + CELL], [lon, lat]]
                feats.append({"type": "Feature", "properties": {"id": did, "name": f"Placeholder cell {n}", "state": "Placeholder"},
                              "geometry": {"type": "Polygon", "coordinates": [ring]}})
                base = 3 + 12 * (1 + math.sin(lon / 6) * math.cos(lat / 5)) + rng.random() * 3
                drift = rng.uniform(-0.05, 0.25)
                pre, post = [], []
                for i, _ in enumerate(YEARS):
                    p = base + drift * i + rng.gauss(0, 0.8)
                    pre.append(round(max(p, 0.5), 2))
                    post.append(round(max(p - 2.5 + rng.gauss(0, 0.5), 0.3), 2))
                data[did] = {"pre": pre, "post": post}
            lon += CELL
        lat += CELL
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "districts.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")))
    write_levels(data)
    print(f"wrote {len(feats)} placeholder cells")


def write_levels(data: dict) -> None:
    (OUT / "levels.json").write_text(json.dumps({
        "meta": {"placeholder": True, "source": "SYNTHETIC - not real data", "unit": "m below ground level",
                 "note": "Replace by running the pipeline against India-WRIS"},
        "years": YEARS, "data": data}, separators=(",", ":")))


if __name__ == "__main__":
    main()

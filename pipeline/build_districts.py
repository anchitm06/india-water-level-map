"""Build public/data/districts.geojson from the Census-2011 district boundaries in
udit-001/india-maps-data (https://github.com/udit-001/india-maps-data).

The source mixes vintages (2011 census districts plus later splits, e.g. Telangana only exists
as its 2016 districts). Features are taken newest-first; an older feature is skipped when more
than half of it is already covered by newer ones, so splits replace their parents. Multi-part
districts are unioned, geometry is simplified, and properties are id (state_code-district_code),
name, state. Usage: python pipeline/build_districts.py [source.geojson]
If no path is given the source is downloaded.
"""
import json
import re
import sys
import urllib.request
from pathlib import Path

from shapely.geometry import mapping, shape
from shapely.ops import unary_union

URL = "https://raw.githubusercontent.com/udit-001/india-maps-data/main/geojson/india.geojson"
OUT = Path(__file__).resolve().parent.parent / "public" / "data" / "districts.geojson"
SIMPLIFY_DEG = 0.01
# The all-India file keeps only a few islands per district (Lakshadweep was just Minicoy), so
# island territories take their geometry from the source's detailed per-state files, simplified
# less so islands a few km across survive.
ISLAND_STATES = ["lakshadweep", "andaman-and-nicobar-islands"]
STATE_URL = "https://raw.githubusercontent.com/udit-001/india-maps-data/main/geojson/states/{}.geojson"
ISLAND_SIMPLIFY_DEG = 0.002


def main() -> None:
    if len(sys.argv) > 1:
        src = json.loads(Path(sys.argv[1]).read_text())
    else:
        src = json.load(urllib.request.urlopen(URL))
    def vintage(p: dict) -> int:
        m = re.search(r"\d{4}", p.get("year") or "")
        return int(m.group()) if m else 0

    # group multi-part districts, then take newest first
    groups: dict[tuple, list] = {}
    for f in src["features"]:
        p = f["properties"]
        if "district" not in p:
            continue
        key = (p["st_code"], p.get("dt_code") or "000", p["district"], vintage(p))
        groups.setdefault(key, [p, []])[1].append(shape(f["geometry"]).buffer(0))
    acc: dict[str, list] = {}
    kept = None
    for key in sorted(groups, key=lambda k: -k[3]):
        p, geoms = groups[key]
        g = unary_union(geoms)
        if kept is not None and kept.intersection(g).area > 0.5 * g.area:
            continue
        kept = g if kept is None else kept.union(g)
        did = f"{key[0]}-{key[1]}"
        while did in acc:
            did += "x"
        acc[did] = [p, [g]]
    islands = {}
    for state in ISLAND_STATES:
        for f in json.load(urllib.request.urlopen(STATE_URL.format(state)))["features"]:
            p = f["properties"]
            islands[f"{p['st_code']}-{p.get('dt_code') or '000'}"] = shape(f["geometry"]).buffer(0)
    feats = []
    for did, (p, geoms) in acc.items():
        if did in islands:
            g = islands[did].simplify(ISLAND_SIMPLIFY_DEG, preserve_topology=True)
        else:
            g = unary_union(geoms).simplify(SIMPLIFY_DEG, preserve_topology=True)
        if g.is_empty:
            continue
        geom = json.loads(json.dumps(mapping(g)), parse_float=lambda s: round(float(s), 3))
        feats.append({"type": "Feature", "properties": {"id": did, "name": p["district"], "state": p["st_nm"]},
                      "geometry": geom})
    OUT.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")))
    print(f"wrote {len(feats)} districts")


if __name__ == "__main__":
    main()

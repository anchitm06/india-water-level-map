"""Fetch India-WRIS station names for the wells in pipeline/raw/readings.csv.

fetch.py keeps only codes, coordinates and levels, and re-fetching everything for names would
take a day. This asks WRIS for single days instead: we know when every well was read, so for each
district it repeatedly picks the date on which the most still-unnamed wells were read and queries
that district's WRIS targets for that one day (a few hundred rows). Every station in a response
gets named, not just the ones looked for. Wells still unnamed get a second pass through the
targets of neighbouring districts, since WRIS district lines differ from our polygons.

    python pipeline/fetch_names.py [--workers 3]

Output: pipeline/raw/station_names.json, {station: {name, village, block, tehsil, district, state,
agency}}, saved after every district, so the run is resumable. Uses fetch.py's throttle (max 2
requests/second across workers). aggregate.py turns these into display names (display_name).
"""
import argparse
import csv
import json
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import district_match  # noqa: E402
import fetch  # noqa: E402

OUT = HERE / "raw" / "station_names.json"
TRIES_OWN = 8  # single-day queries per district, own targets
TRIES_NEIGHBOUR = 1  # per neighbouring district, for wells still unnamed (trial: 3 tries took
                     # more requests than phase 1 for +4% named)
FIELDS = ("stationName", "village", "block", "tehsil", "district", "state", "agencyName")


def station_dates() -> tuple[dict[str, tuple[float, float]], dict[str, set[str]]]:
    """Station -> (lon, lat), and station -> the last reading date in each year-season it was read."""
    pos: dict[str, tuple[float, float]] = {}
    last: dict[tuple[str, str], str] = {}
    with open(HERE / "raw" / "readings.csv", newline="", encoding="utf-8") as fh:
        rows = csv.reader(fh)
        next(rows)
        for sid, lat, lon, date, _ in rows:
            sid = sys.intern(sid)
            if sid not in pos:
                pos[sid] = (float(lon), float(lat))
            key = (sid, date[:4] + ("pre" if date[5:7] <= "06" else "post"))
            if date > last.get(key, ""):
                last[key] = date
    dates: dict[str, set[str]] = defaultdict(set)
    for (sid, _), date in last.items():
        dates[sid].add(date)
    return pos, dates


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=2, help=f"at most {fetch.MAX_WORKERS}")
    ap.add_argument("--only", help="comma-separated district ids (as in districts.geojson), for a trial")
    args = ap.parse_args()
    if not 1 <= args.workers <= fetch.MAX_WORKERS:
        sys.exit(f"--workers must be 1..{fetch.MAX_WORKERS}")
    from shapely.geometry import shape
    from shapely.strtree import STRtree

    names: dict[str, dict] = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    pos, dates = station_dates()
    gj = json.loads((HERE.parent / "public/data/districts.geojson").read_text(encoding="utf-8"))
    ids = [f["properties"]["id"] for f in gj["features"]]
    polys = [shape(f["geometry"]) for f in gj["features"]]
    tree = STRtree(polys)

    # geojson district -> WRIS targets, through the name crosswalk
    matcher = district_match.Matcher()
    targets: dict[str, list[dict]] = defaultdict(list)
    with open(fetch.TARGETS, newline="", encoding="utf-8") as fh:
        for t in fetch.unique_targets(csv.DictReader(fh)):
            p, _ = matcher.match(t["state"], t["district"])
            if p:
                targets[p["id"]].append(t)
    neighbours = {ids[i]: [ids[j] for j in tree.query(polys[i].buffer(0.01)) if j != i] for i in range(len(ids))}

    # Only the wells the site shows, by the district aggregate.py put them in. Wells outside every
    # polygon (often swapped coordinates) were first given to the nearest district: 953 landed in
    # Kutch and used up its tries while 204 real Kutch wells went unnamed.
    by_district: dict[str, list[str]] = defaultdict(list)
    for f in (HERE.parent / "public/data/stations").glob("*.json"):
        by_district[f.stem] = [s["id"] for s in json.loads(f.read_text(encoding="utf-8"))["stations"] if s["id"] in dates]

    lock = threading.Lock()
    stats = Counter()
    stop = threading.Event()

    def query(t: dict, day: str) -> None:
        try:
            rows = fetch.fetch_window(t["state"], t["district"], t["agency"], day, day)
        except Exception as e:  # noqa: BLE001 - logged; a later try or run can still name the wells
            with lock:
                stats["failed"] += 1
                print(f"FAILED {t['district']}/{t['agency']} {day}: {e!r}", file=sys.stderr, flush=True)
                if stats["failed"] >= 20 and stats["failed"] > stats["requests"] // 4:
                    stop.set()
            return
        with lock:
            stats["requests"] += 1
            for r in rows:
                sid = r.get("stationCode")
                if sid and sid not in names:
                    names[sid] = {k: r.get(k) for k in FIELDS}

    def hunt(did: str, via: list[str], tries: int) -> None:
        for _ in range(tries):
            if stop.is_set():
                return
            with lock:
                missing = [s for s in by_district[did] if s not in names]
            if not missing:
                return
            cover = Counter(d for s in missing for d in dates[s])
            day = next((d for d, _ in cover.most_common() if d not in tried[did]), None)
            if day is None:
                return
            tried[did].add(day)
            for v in via:
                for t in targets.get(v, ()):
                    query(t, day)

    tried: dict[str, set[str]] = defaultdict(set)
    done = [0]
    started = time.monotonic()

    def district(did: str, phase: int) -> None:
        if phase == 1:
            hunt(did, [did], TRIES_OWN)
        else:
            for n in neighbours.get(did, ()):
                hunt(did, [n], TRIES_NEIGHBOUR)
        with lock:
            done[0] += 1
            named = sum(1 for s in by_district[did] if s in names)
            tmp = OUT.with_suffix(".tmp")
            tmp.write_text(json.dumps(names, ensure_ascii=False), encoding="utf-8")
            tmp.replace(OUT)
            print(f"[phase {phase}, {done[0]}, {stats['requests']} requests, {(time.monotonic() - started) / 60:.0f} min] "
                  f"{did}: {named}/{len(by_district[did])} named", flush=True)

    todo = sorted(by_district, key=lambda d: -len(by_district[d]))
    if args.only:
        todo = [d for d in todo if d in args.only.split(",")]
    print(f"{sum(len(by_district[d]) for d in todo)} stations in {len(todo)} districts, "
          f"{sum(1 for d in todo for s in by_district[d] if s in names)} already named", flush=True)
    # Phase 1: every district's own targets. Phase 2: neighbours' targets, only for wells still
    # unnamed (phase 1 of the neighbour usually names border wells already, as a side effect).
    with ThreadPoolExecutor(args.workers) as pool:
        for phase in (1, 2):
            futures = [pool.submit(district, d, phase) for d in todo
                       if any(s not in names for s in by_district[d])]
            try:
                while not all(f.done() for f in futures):
                    time.sleep(1)  # keeps Ctrl+C working on Windows
                for f in futures:
                    f.result()
            except KeyboardInterrupt:
                stop.set()
                print("\nstopping; re-run to resume", file=sys.stderr)
            if stop.is_set():
                break
    shown = [s for d in todo for s in by_district[d]]
    found = sum(1 for s in shown if s in names)
    print(f"done: {found}/{len(shown)} wells named ({100 * found / len(shown):.1f}%), {stats['requests']} requests, "
          f"{stats['failed']} failed -> {OUT}")
    if stop.is_set():
        sys.exit(1)


if __name__ == "__main__":
    main()

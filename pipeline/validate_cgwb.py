"""Check our cleaned station values against a CGWB Ground Water Year Book.

The yearbook's annexures give, per state, how many monitoring wells fall in each depth band
(0-2, 2-5, 5-10, 10-20, 20-40, >40 m bgl) for pre-monsoon (May) and November of its year, from
CGWB's manual network in the unconfined aquifer. This recomputes the same distribution from
pipeline/raw/readings.csv, using the station-seasons aggregate.py treats as manual, and prints
the per-state difference.

    python pipeline/validate_cgwb.py path/to/gw_year_book_2023-2024_final.pdf --year 2023

Yearbooks: https://cgwb.gov.in/en/ground-water-level-monitoring (needs an Indian IP, like
India-WRIS). Needs pypdf (pip install pypdf) and shapely. Results of the 2026-10-30 run are in
STATUS.md.
"""
import argparse
import csv
import json
import re
import statistics
import sys
from pathlib import Path

from pypdf import PdfReader

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import aggregate  # noqa: E402
import district_match  # noqa: E402

BANDS = [(0, 2), (2, 5), (5, 10), (10, 20), (20, 40), (40, float("inf"))]
LABEL = ["0-2", "2-5", "5-10", "10-20", "20-40", ">40"]
ROW = re.compile(r"^\s*\d+\s+([A-Za-z][A-Za-z .&]+?)\s+(\d+)((?:\s+\d+\s+\d+(?:\.\d+)?){6})\s*$")


def yearbook_tables(pdf: Path, year: int) -> dict[str, dict]:
    """{season: {state: {"n", "pct"}}} from the unconfined-aquifer depth distribution annexures."""
    titles = {"pre": rf"Pre\s*-?\s*Monsoon\s*{year}", "post": rf"November\s*{year}"}
    out: dict[str, dict] = {}
    for page in PdfReader(pdf).pages:
        text = page.extract_text() or ""
        head = " ".join(text.split()[:40])
        if "Depth to Water Level Distribution of Percentage" not in head or "Confined" in head:
            continue
        for season, pat in titles.items():
            if season not in out and re.search(pat, head):
                rows = {}
                for line in text.splitlines():
                    m = ROW.match(line)
                    if m:
                        nums = m.group(3).split()
                        rows[m.group(1).strip()] = {"n": int(m.group(2)), "pct": [float(nums[i]) for i in range(1, 12, 2)]}
                out[season] = rows
    return out


def our_distribution(year: int) -> dict[str, dict[str, list[float]]]:
    """{season: {state: [levels]}} for manual station-seasons in `year`, by the station's polygon."""
    from shapely.geometry import Point, shape
    from shapely.strtree import STRtree

    gj = json.loads((HERE.parent / "public/data/districts.geojson").read_text(encoding="utf-8"))
    feats = gj["features"]
    tree = STRtree([shape(f["geometry"]) for f in feats])
    pos: dict[str, tuple[float, float]] = {}
    # neighbouring years too, so the jump check sees each station's history
    window = {str(y) for y in range(year - 2, year + 3)}

    def readings():
        with open(HERE / "raw/readings.csv", newline="", encoding="utf-8") as fh:
            rows = csv.reader(fh)
            next(rows)
            for sid, lat, lon, date, level in rows:
                if date[:4] in window:
                    pos.setdefault(sid, (float(lon), float(lat)))
                    yield sys.intern(sid), date, float(level)

    seasonal, _, manual = aggregate.station_seasons(readings())
    out: dict[str, dict[str, list[float]]] = {"pre": {}, "post": {}}
    for (sid, y, season), level in seasonal.items():
        if y == year and (sid, y, season) in manual:
            hit = next(iter(tree.query(Point(pos[sid]), predicate="within")), None)
            if hit is not None:
                out[season].setdefault(feats[hit]["properties"]["state"], []).append(level)
    return out


def pct(vals: list[float]) -> list[float]:
    return [100 * sum(lo <= v < hi for v in vals) / len(vals) for lo, hi in BANDS]


def median_band(p: list[float]) -> int:
    acc = 0.0
    for i, x in enumerate(p):
        acc += x
        if acc >= 50:
            return i
    return len(p) - 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--year", type=int, required=True, help="the yearbook's pre-monsoon / November year")
    args = ap.parse_args()
    cgwb = yearbook_tables(args.pdf, args.year)
    if not cgwb:
        sys.exit("no depth distribution annexures found for that year")
    ours = our_distribution(args.year)
    matcher = district_match.Matcher()
    for season, title in (("pre", f"PRE-MONSOON {args.year} (CGWB: May; ours: Mar-May median)"),
                          ("post", f"POST-MONSOON {args.year} (CGWB: November; ours: Oct-Dec median)")):
        print(f"\n=== {title}")
        print(f"{'state':30} {'CGWB n':>6} {'our n':>6}  {'max band diff (pp)':>18}  median band CGWB / ours")
        both_c, both_o, diffs, agree, compared = [], [], [], 0, 0
        for name, c in sorted(cgwb.get(season, {}).items()):
            state = matcher.state(name) or ("Jammu and Kashmir" if "Jammu" in name else None)
            vals = ours[season].get(state, []) + (ours[season].get("Ladakh", []) if state == "Jammu and Kashmir" else [])
            if not vals:
                print(f"{name[:30]:30} {c['n']:6} {0:6}  no manual wells in India-WRIS")
                continue
            p = pct(vals)
            d = max(abs(a - b) for a, b in zip(p, c["pct"]))
            mc, mo = median_band(c["pct"]), median_band(p)
            compared += 1
            agree += mc == mo
            if c["n"] >= 50 and len(vals) >= 50:
                diffs.append(d)
            both_c.append((c["n"], c["pct"]))
            both_o.extend(vals)
            print(f"{name[:30]:30} {c['n']:6} {len(vals):6}  {d:18.1f}  {LABEL[mc]:>5} / {LABEL[mo]:<5}{'' if mc == mo else '  <- differs'}")
        if not both_o:
            continue
        nat = [sum(n * p[i] for n, p in both_c) / sum(n for n, _ in both_c) for i in range(len(BANDS))]
        print(f"all compared states, % per band  CGWB: {' '.join(f'{x:5.1f}' for x in nat)}  (n={sum(n for n, _ in both_c)})")
        print(f"                                 ours: {' '.join(f'{x:5.1f}' for x in pct(both_o))}  (n={len(both_o)})")
        print(f"median band agrees in {agree}/{compared} states; states with >=50 wells on both sides: "
              f"median of max band difference {statistics.median(diffs):.1f} pp")


if __name__ == "__main__":
    main()

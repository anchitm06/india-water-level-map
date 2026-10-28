"""Download groundwater-level readings from the India-WRIS public API into pipeline/raw/readings.csv.

API (from https://indiawris.gov.in/swagger-ui/index.html, "Data API Based On Admin Hierarchy"):
  POST /Dataset/Ground Water Level?stateName=&districtName=&agencyName=&startdate=&enddate=&download=true&page=&size=
  size max 1000; with download=true the body is a bare JSON list of readings.

The API is queried per (state, district, agency), so you need a targets file listing them:
    pipeline/targets.csv   columns: state,district,agency
Build it with `python pipeline/fetch.py --discover > pipeline/targets.csv` (lists states and
districts; the agency column must still be filled in) or by hand from the site's drop-downs.

Only pre-monsoon (Mar-May) and post-monsoon (Oct-Dec) readings are requested, and telemetric
(minute-level) readings are reduced to one median per station per day while streaming, so output
stays small. The run is resumable: finished (target, year, season) windows are logged in
pipeline/raw/done.log.

Output columns (what aggregate.py reads): station_id,lat,lon,date,level_m_bgl
ASSUMPTION to verify against CGWB/WRIS docs: dataValue (unit "m") is depth to water below ground
level for datatypeCode GGZ. Rows whose unit is not "m" are skipped.

Run this from a machine that can reach indiawris.gov.in (an Indian IP); the Claude cloud sandbox
and GitHub-hosted runners cannot.
"""
import argparse
import csv
import json
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

BASE = "https://indiawris.gov.in"
RAW = Path(__file__).resolve().parent / "raw"
TARGETS = Path(__file__).resolve().parent / "targets.csv"
PAGE_SIZE = 1000
SEASONS = {"pre": ("03-01", "05-31"), "post": ("10-01", "12-31")}


def call(method: str, path: str, params: dict | None = None, body=None, retries: int = 4):
    url = BASE + urllib.parse.quote(path) + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(body).encode() if body is not None else (b"" if method == "POST" else None)
    headers = {"Accept": "application/json", "User-Agent": "india-water-level-map/0.1 (research; contact via repo)"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, method=method, headers=headers)
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.load(resp)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            if isinstance(e, urllib.error.HTTPError) and e.code in (400, 401, 403, 404):
                raise
            if attempt == retries - 1:
                raise
            time.sleep(2 ** (attempt + 1))


def rows_of(payload) -> list[dict]:
    """download=true returns a bare list; otherwise {statusCode, message, data}."""
    if isinstance(payload, list):
        return payload
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("content", "data", "records"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def fetch_window(state: str, district: str, agency: str, start: str, end: str) -> list[dict]:
    out, page = [], 0
    while True:
        payload = call("POST", "/Dataset/Ground Water Level", {
            "stateName": state, "districtName": district, "agencyName": agency,
            "startdate": start, "enddate": end, "download": "true", "page": page, "size": PAGE_SIZE})
        batch = rows_of(payload)
        out.extend(batch)
        if len(batch) < PAGE_SIZE:
            return out
        page += 1
        time.sleep(0.5)


def reduce_daily(rows: list[dict]) -> list[tuple[str, float, float, str, float]]:
    """-> (station_id, lat, lon, YYYY-MM-DD, median level) with one row per station per day."""
    by_day: dict[tuple, list[float]] = defaultdict(list)
    pos: dict[str, tuple[float, float]] = {}
    for r in rows:
        t, v = r.get("dataTime"), r.get("dataValue")
        if not isinstance(t, dict) or v is None or r.get("unit") != "m":
            continue
        if r.get("latitude") is None or r.get("longitude") is None:
            continue
        sid = r["stationCode"]
        pos[sid] = (r["latitude"], r["longitude"])
        by_day[(sid, f"{t['year']:04d}-{t['monthValue']:02d}-{t['dayOfMonth']:02d}")].append(float(v))
    return [(sid, *pos[sid], day, round(statistics.median(vs), 3)) for (sid, day), vs in sorted(by_day.items())]


def discover() -> None:
    """Print every (state, district) India-WRIS has groundwater data for, as CSV, so targets.csv
    can be built. The master endpoints are not in the swagger; these bodies were found by trial on
    2026-10-28. The agency list endpoint is still unknown (districAgencyList is a 404), so the
    agency column is left empty: fill it from the site's drop-down or the browser network tab."""
    body = {"datasetcode": "GWATERLVL"}
    w = csv.writer(sys.stdout)
    w.writerow(["state", "district", "agency"])
    for s in rows_of(call("POST", "/masterState/StateList", body=body)):
        districts = rows_of(call("POST", "/masterDistrict/getDistrictbyState", body={**body, "statecode": s["statecode"]}))
        for d in districts:
            w.writerow([s["state"], d["districtname"], ""])
        time.sleep(0.5)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--from-year", type=int, default=2000)
    ap.add_argument("--to-year", type=int, default=time.gmtime().tm_year)
    args = ap.parse_args()
    if args.discover:
        return discover()
    if not TARGETS.exists():
        sys.exit(f"missing {TARGETS}; create it (state,district,agency) or run --discover")

    RAW.mkdir(exist_ok=True)
    done_path = RAW / "done.log"
    done = set(done_path.read_text().splitlines()) if done_path.exists() else set()
    out_path = RAW / "readings.csv"
    new_file = not out_path.exists()
    with open(out_path, "a", newline="") as out, open(done_path, "a") as dl, open(TARGETS, newline="") as tf:
        w = csv.writer(out)
        if new_file:
            w.writerow(["station_id", "lat", "lon", "date", "level_m_bgl"])
        for t in csv.DictReader(tf):
            for year in range(args.from_year, args.to_year + 1):
                for season, (s, e) in SEASONS.items():
                    key = "|".join([t["state"], t["district"], t["agency"], str(year), season])
                    if key in done:
                        continue
                    rows = fetch_window(t["state"], t["district"], t["agency"], f"{year}-{s}", f"{year}-{e}")
                    w.writerows(reduce_daily(rows))
                    out.flush()
                    dl.write(key + "\n")
                    dl.flush()
                    print(f"{key}: {len(rows)} raw readings", flush=True)
                    time.sleep(0.5)


if __name__ == "__main__":
    main()

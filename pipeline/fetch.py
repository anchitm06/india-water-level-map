"""Download groundwater-level readings from the India-WRIS public API into pipeline/raw/readings.csv.

API (from https://indiawris.gov.in/swagger-ui/index.html, "Data API Based On Admin Hierarchy"):
  POST /Dataset/Ground Water Level?stateName=&districtName=&agencyName=&startdate=&enddate=&download=true&page=&size=
  size max 1000; with download=true the body is a bare JSON list of readings.

The API is queried per (state, district, agency), so you need a targets file listing them:
    pipeline/targets.csv   columns: state,district,agency
Build it with `python pipeline/fetch.py --discover > pipeline/targets.csv`.

Only pre-monsoon (Mar-May) and post-monsoon (Oct-Dec) readings are kept, and telemetric
(minute-level) readings are reduced to one median per station per day while streaming, so output
stays small. The run is resumable: finished (target, year, season) windows are logged in
pipeline/raw/done.log, so Ctrl+C or a shutdown loses at most the windows in flight.

Load on the server (a government site, so be gentle):
  - Before --seasonal-from (default 2022) data is manual, a few rows per station per year, so one
    Mar-Dec request per year replaces two seasonal ones. From then on telemetric data is heavy and
    each season is requested on its own so the monsoon months are not downloaded.
  - All workers share one throttle: at most one request per MIN_INTERVAL_S. --workers is capped
    at 3; extra workers only overlap slow responses, they do not raise the request rate.
  - Failed windows are retried with backoff, skipped and picked up by the next run. After
    MAX_CONSECUTIVE_FAILURES in a row the run stops (the server is probably down or blocking).

Data before ~1985 is a handful of wells per district (probed 2026-10-28), hence --from-year 1985.
Try one state first:  python pipeline/fetch.py --state Delhi

Output columns (what aggregate.py reads): station_id,lat,lon,date,level_m_bgl
Several workers append to readings.csv, so rows are grouped per window, not sorted.
ASSUMPTION to verify against CGWB/WRIS docs: |dataValue| (unit "m") is depth to water below ground
level for datatypeCode GGZ; see clean_level. Rows whose unit is not "m" are skipped.

Run this from a machine that can reach indiawris.gov.in (an Indian IP); the Claude cloud sandbox
and GitHub-hosted runners cannot.
"""
import argparse
import csv
import json
import statistics
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = "https://indiawris.gov.in"
RAW = Path(__file__).resolve().parent / "raw"
TARGETS = Path(__file__).resolve().parent / "targets.csv"
PAGE_SIZE = 1000
SEASONS = {"pre": ("03-01", "05-31"), "post": ("10-01", "12-31")}
MAX_DEPTH_M = 200  # deepest Indian water tables are ~150 m; seen: -1000 sentinels, a sensor drifting to -1124
MIN_INTERVAL_S = 0.5  # across all workers: at most 2 requests/second
MAX_WORKERS = 3
MAX_CONSECUTIVE_FAILURES = 5


class Throttle:
    """Spaces request starts at least `interval` seconds apart across threads."""

    def __init__(self, interval: float):
        self.interval, self.next, self.lock = interval, 0.0, threading.Lock()

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            start = max(now, self.next)
            self.next = start + self.interval
        time.sleep(start - now)


THROTTLE = Throttle(MIN_INTERVAL_S)


def call(method: str, path: str, params: dict | None = None, body=None, retries: int = 4):
    url = BASE + urllib.parse.quote(path) + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(body).encode() if body is not None else (b"" if method == "POST" else None)
    headers = {"Accept": "application/json", "User-Agent": "india-water-level-map/0.1 (research; contact via repo)"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    for attempt in range(retries):
        THROTTLE.wait()
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


def clean_level(r: dict) -> float | None:
    """dataValue -> metres below ground, or None if unusable. Seen in live data (2026-10-28):
    CGWB telemetric stations mostly report depth as negative, some as positive, so take abs;
    -1000 is a no-data sentinel and faulty sensors drift to hundreds of metres; exact 0.0 and
    readings at/below well depth are sensor artefacts."""
    v = r.get("dataValue")
    if v is None:
        return None
    v = abs(float(v))
    well = r.get("wellDepth")
    if v == 0 or v >= MAX_DEPTH_M or (well and v >= well):
        return None
    return v


def reduce_daily(rows: list[dict]) -> list[tuple[str, float, float, str, float]]:
    """-> (station_id, lat, lon, YYYY-MM-DD, median level) with one row per station per day."""
    by_day: dict[tuple, list[float]] = defaultdict(list)
    pos: dict[str, tuple[float, float]] = {}
    for r in rows:
        t, v = r.get("dataTime"), clean_level(r)
        if not isinstance(t, dict) or v is None or r.get("unit") != "m":
            continue
        if r.get("latitude") is None or r.get("longitude") is None:
            continue
        sid = r["stationCode"]
        pos[sid] = (r["latitude"], r["longitude"])
        by_day[(sid, f"{t['year']:04d}-{t['monthValue']:02d}-{t['dayOfMonth']:02d}")].append(v)
    return [(sid, *pos[sid], day, round(statistics.median(vs), 3)) for (sid, day), vs in sorted(by_day.items())]


def discover() -> None:
    """Print every (state, district, agency) India-WRIS has groundwater data for, as the CSV that
    targets.csv expects. The master endpoints are not in the swagger; the bodies were taken from
    the site's own requests on 2026-10-28."""
    body = {"datasetcode": "GWATERLVL"}
    w = csv.writer(sys.stdout)
    w.writerow(["state", "district", "agency"])
    seen: set[tuple] = set()
    for s in rows_of(call("POST", "/masterState/StateList", body=body)):
        districts = rows_of(call("POST", "/masterDistrict/getDistrictbyState", body={**body, "statecode": s["statecode"]}))
        for d in districts:
            agencies = rows_of(call("POST", "/masterAgency/AgencyListInAnyCase", body={**body, "district_id": d["district_id"]}))
            for t in unique_targets(({"state": s["state"], "district": d["districtname"], "agency": a["agencyname"]}
                                     for a in agencies), seen):
                w.writerow([t["state"], t["district"], t["agency"]])
            sys.stdout.flush()


def unique_targets(targets, seen: set[tuple] | None = None) -> list[dict]:
    """WRIS lists some districts twice in different case (Betul / BETUL) and its data API ignores
    case, so both would download the same readings. Keep the first spelling."""
    seen = set() if seen is None else seen
    out = []
    for t in targets:
        key = (t["state"].lower(), t["district"].lower(), t["agency"].lower())
        if key not in seen:
            seen.add(key)
            out.append(t)
    return out


def season_of(r: dict) -> str | None:
    t = r.get("dataTime")
    month = t.get("monthValue") if isinstance(t, dict) else None
    for name, (s, e) in SEASONS.items():
        if month is not None and int(s[:2]) <= month <= int(e[:2]):
            return name
    return None


def windows(year: int, seasonal: bool) -> list[tuple[str, str, list[str]]]:
    """-> (start, end, seasons covered). One Mar-Dec window, or one per season."""
    if not seasonal:
        first, last = min(SEASONS.values()), max(SEASONS.values())
        return [(f"{year}-{first[0]}", f"{year}-{last[1]}", list(SEASONS))]
    return [(f"{year}-{s}", f"{year}-{e}", [name]) for name, (s, e) in SEASONS.items()]


class Run:
    """Shared state for the worker threads: output files, progress, and the circuit breaker."""

    def __init__(self, out, done_log, total: int):
        self.writer, self.out, self.done_log = csv.writer(out), out, done_log
        self.lock, self.stop = threading.Lock(), threading.Event()
        self.total, self.finished, self.failures, self.started = total, 0, 0, time.monotonic()

    def record(self, keys: list[str], readings: list, raw_count: int) -> None:
        with self.lock:
            self.writer.writerows(readings)
            self.out.flush()
            self.done_log.write("".join(k + "\n" for k in keys))
            self.done_log.flush()
            self.failures = 0
            self.finished += len(keys)
            rate = self.finished / (time.monotonic() - self.started)
            eta_h = (self.total - self.finished) / rate / 3600
            print(f"[{self.finished}/{self.total}, ~{eta_h:.1f} h left] {keys[0]} +{len(keys) - 1}: "
                  f"{raw_count} raw -> {len(readings)} daily", flush=True)

    def fail(self, key: str, err: Exception) -> None:
        with self.lock:
            self.failures += 1
            print(f"FAILED {key}: {err!r} (will retry next run)", file=sys.stderr, flush=True)
            if self.failures >= MAX_CONSECUTIVE_FAILURES:
                print(f"{self.failures} failures in a row; stopping. Re-run later to resume.", file=sys.stderr, flush=True)
                self.stop.set()


def fetch_target(run: Run, t: dict, years: range, seasonal_from: int, done: set[str]) -> None:
    for year in years:
        for start, end, seasons in windows(year, year >= seasonal_from):
            keys = ["|".join([t["state"], t["district"], t["agency"], str(year), s]) for s in seasons]
            if all(k in done for k in keys):
                continue
            if run.stop.is_set():
                return
            try:
                rows = fetch_window(t["state"], t["district"], t["agency"], start, end)
            except Exception as e:  # noqa: BLE001 - logged; the window stays undone for the next run
                run.fail(keys[0], e)
                continue
            rows = [r for r in rows if season_of(r) in seasons]
            run.record(keys, reduce_daily(rows), len(rows))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--from-year", type=int, default=1985)
    ap.add_argument("--to-year", type=int, default=time.gmtime().tm_year)
    ap.add_argument("--seasonal-from", type=int, default=2022,
                    help="from this year on, request each season separately (telemetric data is heavy)")
    ap.add_argument("--workers", type=int, default=2, help=f"parallel targets, at most {MAX_WORKERS}")
    ap.add_argument("--state", help="only fetch targets in this state (as written in targets.csv)")
    args = ap.parse_args()
    if args.discover:
        return discover()
    if not TARGETS.exists():
        sys.exit(f"missing {TARGETS}; create it (state,district,agency) or run --discover")
    if not 1 <= args.workers <= MAX_WORKERS:
        sys.exit(f"--workers must be 1..{MAX_WORKERS} (the server is a public government site)")

    with open(TARGETS, newline="", encoding="utf-8") as tf:
        targets = unique_targets(t for t in csv.DictReader(tf) if not args.state or t["state"].lower() == args.state.lower())
    if not targets:
        sys.exit(f"no targets for state {args.state!r}")
    RAW.mkdir(exist_ok=True)
    done_path = RAW / "done.log"
    done = set(done_path.read_text(encoding="utf-8").splitlines()) if done_path.exists() else set()
    years = range(args.from_year, args.to_year + 1)
    total = sum(1 for t in targets for y in years for s in SEASONS
                if "|".join([t["state"], t["district"], t["agency"], str(y), s]) not in done)
    print(f"{len(targets)} targets, {total} season windows to fetch, {args.workers} workers", flush=True)

    out_path = RAW / "readings.csv"
    new_file = not out_path.exists()
    with open(out_path, "a", newline="", encoding="utf-8") as out, open(done_path, "a", encoding="utf-8") as dl:
        if new_file:
            csv.writer(out).writerow(["station_id", "lat", "lon", "date", "level_m_bgl"])
        run = Run(out, dl, total)
        pool = ThreadPoolExecutor(args.workers)
        futures = [pool.submit(fetch_target, run, t, years, args.seasonal_from, done) for t in targets]
        try:
            while not all(f.done() for f in futures):
                time.sleep(1)  # unlike f.result(), sleep lets Ctrl+C through on Windows
            for f in futures:
                f.result()
        except KeyboardInterrupt:
            print("\nstopping after the requests in flight; re-run to resume", file=sys.stderr, flush=True)
            run.stop.set()
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
    if run.stop.is_set():
        sys.exit(1)


if __name__ == "__main__":
    main()

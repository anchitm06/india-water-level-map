import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fetch import Throttle, clean_level, reduce_daily, rows_of, season_of, unique_targets, windows  # noqa: E402

rows = json.loads((Path(__file__).parent / "sample_gwl.json").read_text())


def test_reduce_daily_one_row_per_station_day():
    out = reduce_daily(rows)
    assert len({(r[0], r[3]) for r in out}) == len(out)
    assert all(r[3].count("-") == 2 and 8 < r[1] < 38 for r in out)


def test_rows_of_shapes():
    assert rows_of(rows) == rows
    assert rows_of({"statusCode": 0, "data": rows}) == rows
    assert rows_of({"data": {"content": rows}}) == rows


def test_clean_level():
    assert clean_level({"dataValue": -9.782}) == 9.782
    assert clean_level({"dataValue": 25.85}) == 25.85
    assert clean_level({"dataValue": -1000.0}) is None
    assert clean_level({"dataValue": -367.7}) is None
    assert clean_level({"dataValue": 0.0}) is None
    assert clean_level({"dataValue": None}) is None
    assert clean_level({"dataValue": 44.2, "wellDepth": 45.0}) == 44.2
    assert clean_level({"dataValue": 45.0, "wellDepth": 45.0}) is None



def test_windows_and_seasons():
    assert windows(2010, seasonal=False) == [("2010-03-01", "2010-12-31", ["pre", "post"])]
    assert windows(2023, seasonal=True) == [("2023-03-01", "2023-05-31", ["pre"]), ("2023-10-01", "2023-12-31", ["post"])]
    months = {m: season_of({"dataTime": {"monthValue": m}}) for m in range(1, 13)}
    assert [m for m, s in months.items() if s == "pre"] == [3, 4, 5]
    assert [m for m, s in months.items() if s == "post"] == [10, 11, 12]
    assert season_of({}) is None


def test_unique_targets_ignores_case():
    ts = [{"state": "MP", "district": "Betul", "agency": "CGWB"}, {"state": "MP", "district": "BETUL", "agency": "CGWB"},
          {"state": "MP", "district": "Betul", "agency": "MP GW"}]
    assert [t["district"] + "/" + t["agency"] for t in unique_targets(ts)] == ["Betul/CGWB", "Betul/MP GW"]


def test_throttle_spaces_requests():
    th = Throttle(0.05)
    start = time.monotonic()
    for _ in range(4):
        th.wait()
    assert th.next >= start + 0.2 - 1e-6  # four slots booked back to back (float-rounding slack)
    assert time.monotonic() - start >= 0.1  # loose: Windows clocks tick every ~15 ms


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)

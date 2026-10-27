import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fetch import reduce_daily, rows_of  # noqa: E402

rows = json.loads((Path(__file__).parent / "sample_gwl.json").read_text())


def test_reduce_daily_one_row_per_station_day():
    out = reduce_daily(rows)
    assert len({(r[0], r[3]) for r in out}) == len(out)
    assert all(r[3].count("-") == 2 and 8 < r[1] < 38 for r in out)


def test_rows_of_shapes():
    assert rows_of(rows) == rows
    assert rows_of({"statusCode": 0, "data": rows}) == rows
    assert rows_of({"data": {"content": rows}}) == rows

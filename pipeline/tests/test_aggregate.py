import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from aggregate import far_from, station_seasons  # noqa: E402


def days(sid, year, month, levels):
    return [(sid, f"{year}-{month:02d}-{d + 1:02d}", v) for d, v in enumerate(levels)]


def test_far_from_has_a_floor_for_flat_series():
    far = far_from([8.0, 8.0, 8.0], k=5, floor=2.0)
    assert not far(9.5) and far(174.0)


def test_daily_spike_removed_before_season_median():
    seasonal, dropped = station_seasons(days("S1", 2023, 10, [8.1, 8.2, 8.0, 174.0, 8.3, 8.1]))
    assert seasonal == {("S1", 2023, "post"): 8.1}
    assert dropped["daily spikes"] == 1


def test_station_counts_once_per_season_and_duplicates_collapse():
    rows = days("T", 2024, 3, [10.0] * 90) + days("T", 2024, 3, [10.0] * 90) + [("M", "2024-05-02", 30.0)]
    seasonal, _ = station_seasons(rows)
    assert seasonal == {("T", 2024, "pre"): 10.0, ("M", 2024, "pre"): 30.0}


def test_jump_against_own_history_removed():
    rows = [("W", f"{y}-11-15", 8.0 + 0.1 * (y - 2000)) for y in range(2000, 2010)] + [("W", "2010-11-15", 110.3)]
    seasonal, dropped = station_seasons(rows)
    assert ("W", 2010, "post") not in seasonal and len(seasonal) == 10
    assert dropped["station-season jumps"] == 1


def test_long_genuine_decline_kept():
    # 1 m/year for 35 years, as in over-pumped parts of Punjab or Rajasthan
    rows = [("D", f"{y}-05-10", 10.0 + (y - 1990)) for y in range(1990, 2025)]
    seasonal, dropped = station_seasons(rows)
    assert len(seasonal) == 35 and not dropped


def test_isolated_season_before_a_gap_kept():
    # one 1994 reading, then nothing until 2005 at a much deeper level (seen in Delhi)
    rows = [("G", "1994-11-15", 10.0)] + [("G", f"{y}-11-15", 32.0) for y in range(2005, 2012)]
    seasonal, dropped = station_seasons(rows)
    assert ("G", 1994, "post") in seasonal and not dropped


def test_recovery_kept():
    rows = [("R", f"{y}-11-15", v) for y, v in zip(range(2010, 2023), [30, 30, 29, 28, 27, 26, 24, 22, 20, 18, 16, 14, 14])]
    seasonal, dropped = station_seasons(rows)
    assert len(seasonal) == 13 and not dropped


def test_off_season_zero_and_out_of_range_ignored():
    rows = [("X", "2020-07-01", 5.0), ("X", "2020-04-01", 0.0), ("X", "2020-04-02", 250.0), ("X", "2020-04-03", 6.0)]
    assert station_seasons(rows)[0] == {("X", 2020, "pre"): 6.0}


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)

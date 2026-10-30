import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from aggregate import district_series, far_from, station_seasons  # noqa: E402

M1, M2, M3, M4 = "M1", "M2", "M3", "M4"  # manually read wells in the district_series tests


def hand(by_year):
    return {y: {s for s in stations if s.startswith("M")} for y, stations in by_year.items()}


def days(sid, year, month, levels):
    return [(sid, f"{year}-{month:02d}-{d + 1:02d}", v) for d, v in enumerate(levels)]


def test_far_from_has_a_floor_for_flat_series():
    far = far_from([8.0, 8.0, 8.0], k=5, floor=2.0)
    assert not far(9.5) and far(174.0)


def test_daily_spike_removed_before_season_median():
    seasonal, dropped, _ = station_seasons(days("S1", 2023, 10, [8.1, 8.2, 8.0, 174.0, 8.3, 8.1]))
    assert seasonal == {("S1", 2023, "post"): 8.1}
    assert dropped["daily spikes"] == 1


def test_station_counts_once_per_season_and_duplicates_collapse():
    rows = days("T", 2024, 3, [10.0] * 90) + days("T", 2024, 3, [10.0] * 90) + [("M", "2024-05-02", 30.0)]
    seasonal, _, _ = station_seasons(rows)
    assert seasonal == {("T", 2024, "pre"): 10.0, ("M", 2024, "pre"): 30.0}


def test_jump_against_own_history_removed():
    rows = [("W", f"{y}-11-15", 8.0 + 0.1 * (y - 2000)) for y in range(2000, 2010)] + [("W", "2010-11-15", 110.3)]
    seasonal, dropped, _ = station_seasons(rows)
    assert ("W", 2010, "post") not in seasonal and len(seasonal) == 10
    assert dropped["station-season jumps"] == 1


def test_long_genuine_decline_kept():
    # 1 m/year for 35 years, as in over-pumped parts of Punjab or Rajasthan
    rows = [("D", f"{y}-05-10", 10.0 + (y - 1990)) for y in range(1990, 2025)]
    seasonal, dropped, _ = station_seasons(rows)
    assert len(seasonal) == 35 and not dropped


def test_isolated_season_before_a_gap_kept():
    # one 1994 reading, then nothing until 2005 at a much deeper level (seen in Delhi)
    rows = [("G", "1994-11-15", 10.0)] + [("G", f"{y}-11-15", 32.0) for y in range(2005, 2012)]
    seasonal, dropped, _ = station_seasons(rows)
    assert ("G", 1994, "post") in seasonal and not dropped


def test_recovery_kept():
    rows = [("R", f"{y}-11-15", v) for y, v in zip(range(2010, 2023), [30, 30, 29, 28, 27, 26, 24, 22, 20, 18, 16, 14, 14])]
    seasonal, dropped, _ = station_seasons(rows)
    assert len(seasonal) == 13 and not dropped


def test_off_season_zero_and_out_of_range_ignored():
    rows = [("X", "2020-07-01", 5.0), ("X", "2020-04-01", 0.0), ("X", "2020-04-02", 250.0), ("X", "2020-04-03", 6.0)]
    assert station_seasons(rows)[0] == {("X", 2020, "pre"): 6.0}


def test_manual_needs_few_reading_days_and_a_lat_lon_code():
    rows = [("283745077141501", "2023-05-10", 5.0)] + days("224432870429748", 2023, 4, [9.0] * 30) + [("RJ1234", "2023-11-02", 4.0)]
    _, _, manual = station_seasons(rows)
    # 30 daily readings = telemetric even with a lat/lon code; a state code read once is not CGWB's network
    assert manual == {("283745077141501", 2023, "pre")}


def test_new_deep_wells_do_not_fake_a_decline():
    # 4 shallow manual wells, flat at ~5 m; from 2022 six deep telemetric wells (~20 m) join and
    # three manual wells stay. A plain median would jump from 5 to 20.
    by_year = {y: {M1: 5.0, M2: 5.2, M3: 4.8, M4: 5.1} for y in range(2018, 2022)}
    for y in range(2022, 2025):
        by_year[y] = {M1: 5.0, M2: 5.2, M3: 4.8, **{f"TEL{i}": 20.0 + i for i in range(6)}}
    levels, mixed = district_series(by_year, list(range(2018, 2025)), hand(by_year))
    assert all(abs(v - 5.05) < 0.01 for v in levels) and not any(mixed)


def test_too_few_shared_wells_restarts_but_stays_on_manual_wells():
    by_year = {y: {M1: 5.0, M2: 5.2, M3: 4.8, M4: 5.1} for y in range(2018, 2022)}
    for y in range(2022, 2025):  # only 2 manual wells carry over: below MIN_PAIRS, chain restarts
        by_year[y] = {M1: 5.0, M2: 5.2, **{f"TEL{i}": 20.0 + i for i in range(6)}}
    levels, mixed = district_series(by_year, list(range(2018, 2025)), hand(by_year))
    assert levels == [5.05] * 7 and mixed == [0] * 4 + [1] * 3  # 2 manual wells can't pin; level carried on


def test_rotating_wells_carry_the_trend():
    # each year measures a sliding window of 4 wells at very different depths (5, 10, 15 m ...),
    # all deepening 1 m/year. A plain median climbs 6 m/year; the chain recovers 1 m/year.
    by_year = {2000 + i: {f"S{k}": 5.0 * k + i for k in range(i, i + 4)} for i in range(6)}
    levels, mixed = district_series(by_year, list(range(2000, 2006)), hand(by_year))
    assert levels == [7.5, 8.5, 9.5, 10.5, 11.5, 12.5]
    assert all(mixed)  # no manual wells: pinned to the all-station median, flagged


def test_new_network_after_short_gap_continues_previous_level():
    # manual wells to 2021, then only new deep telemetric wells from 2023: no shared stations
    by_year = {2020: {M1: 5.0, M2: 6.0, M3: 7.0}, 2021: {M1: 5.5, M2: 6.5, M3: 7.5},
               2023: {"T1": 30.0, "T2": 31.0, "T3": 32.0}, 2024: {"T1": 31.0, "T2": 32.0, "T3": 33.0}}
    levels, mixed = district_series(by_year, [2020, 2021, 2022, 2023, 2024], hand(by_year))
    assert levels == [6.0, 6.5, None, 6.5, 7.5]  # trend from the new wells, level carried over
    assert mixed == [0, 0, 0, 1, 1]


def test_long_gap_without_manual_wells_pins_to_own_median():
    by_year = {2000: {M1: 5.0, M2: 6.0, M3: 7.0}, 2001: {M1: 5.5, M2: 6.5, M3: 7.5},
               2023: {"T1": 30.0, "T2": 31.0, "T3": 32.0}, 2024: {"T1": 31.0, "T2": 32.0, "T3": 33.0}}
    levels, mixed = district_series(by_year, [2000, 2001, 2002, 2023, 2024], hand(by_year))
    assert levels == [6.0, 6.5, None, 31.0, 32.0]
    assert mixed == [0, 0, 0, 1, 1]


def test_one_or_two_manual_wells_do_not_pin_a_run():
    # a sparse telemetric well that reported on 2 days looks manual; it must not set the level
    by_year = {2020: {M1: 8.0, M2: 8.5, M3: 9.0}, 2021: {M1: 8.2, M2: 8.7, M3: 9.2},
               2023: {"T1": 20.0, "T2": 21.0, "M9": 2.0}, 2024: {"T1": 20.5, "T2": 21.5, "M9": 2.5}}
    levels, mixed = district_series(by_year, [2020, 2021, 2022, 2023, 2024], hand(by_year))
    assert levels == [8.5, 8.7, None, 8.7, 9.2] and mixed == [0, 0, 0, 1, 1]


def test_manual_minority_does_not_pin_a_run():
    # Delhi 2026: 3 "manual" (sparse telemetric) wells among 25 stations
    by_year = {2020: {M1: 8.0, M2: 8.5, M3: 9.0}, 2021: {M1: 8.2, M2: 8.7, M3: 9.2},
               2023: {**{f"T{i}": 20.0 + i for i in range(22)}, "M7": 1.6, "M8": 2.1, "M9": 6.8}}
    levels, mixed = district_series(by_year, [2020, 2021, 2022, 2023], hand(by_year))
    assert levels == [8.5, 8.7, None, 8.7] and mixed == [0, 0, 0, 1]


def test_empty_district():
    assert district_series({}, [2000, 2001]) == ([None, None], [0, 0])


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)

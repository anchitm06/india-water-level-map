"""Nearest named place for each well, so the site can say "near Hampur" instead of a station code.

India-WRIS returns station names, but fetch.py does not keep them and re-fetching takes a day,
so names come from the GeoNames gazetteer (https://www.geonames.org, CC BY 4.0, ~550k Indian
villages and towns): half the wells are within 0.8 km of a named place, 89% within 5 km
(checked Oct 2026).

    python pipeline/place_names.py      # downloads pipeline/raw/geonames/IN.txt (16 MB zip)

aggregate.py uses it when that file exists.
"""
import csv
import io
import math
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path

GEONAMES = Path(__file__).resolve().parent / "raw" / "geonames" / "IN.txt"
URL = "https://download.geonames.org/export/dump/IN.zip"
SKIP = {"PPLQ", "PPLH", "PPLW", "PPLCH"}  # abandoned, historical, destroyed, historical capital
MAX_KM = 10.0
CELL = 0.1  # degrees; ~11 km, so a 3x3 block of cells covers MAX_KM


class Gazetteer:
    def __init__(self, path: Path = GEONAMES):
        csv.field_size_limit(10 ** 7)  # the alternate-names column can be long
        self.grid: dict[tuple[int, int], list[tuple[str, float, float]]] = defaultdict(list)
        with open(path, encoding="utf-8", newline="") as fh:
            for r in csv.reader(fh, delimiter="\t", quoting=csv.QUOTE_NONE):
                if r[6] == "P" and r[7] not in SKIP:
                    lat, lon = float(r[4]), float(r[5])
                    self.grid[(int(lat / CELL), int(lon / CELL))].append((r[2], lat, lon))  # ASCII name

    def nearest(self, lat: float, lon: float) -> tuple[str, float] | None:
        """(place name, km) of the closest populated place within MAX_KM, else None."""
        best = None
        cy, cx = int(lat / CELL), int(lon / CELL)
        kx = 111.32 * math.cos(math.radians(lat))
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for name, plat, plon in self.grid.get((cy + dy, cx + dx), ()):
                    d = math.hypot((plat - lat) * 110.57, (plon - lon) * kx)
                    if d <= MAX_KM and (best is None or d < best[1]):
                        best = (name, d)
        return best


def download() -> None:
    GEONAMES.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(URL, timeout=300) as resp:
        GEONAMES.write_bytes(zipfile.ZipFile(io.BytesIO(resp.read())).read("IN.txt"))
    print(f"wrote {GEONAMES}")


if __name__ == "__main__":
    download()

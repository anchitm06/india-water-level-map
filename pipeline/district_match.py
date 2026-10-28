"""Match India-WRIS (state, district) names to the districts in public/data/districts.geojson.

India-WRIS uses older / alternative spellings (Gurgaon, Orissa, EAST for a Delhi district), so
names are resolved in this order and the method is recorded:
  alias   pipeline/district_aliases.csv  (state,wris_name,geojson_name[,geojson_state])  - reviewed by hand
  exact   same normalized name within the state
  fuzzy   difflib ratio >= FUZZY_CUTOFF within the state - REVIEW these before trusting them
  none    no match; add a row to district_aliases.csv
Several WRIS districts may map to one geojson district (e.g. all of Delhi's).

Note aggregate.py assigns readings to districts by lat/lon, not by name; this crosswalk is for
building pipeline/targets.csv and for sanity-checking the polygons against WRIS's own labels.

Usage:
    python pipeline/district_match.py [wris_districts.csv]   # columns state,district (default targets.csv)
Writes pipeline/district_crosswalk.csv and prints a summary.
"""
import csv
import difflib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GEOJSON = HERE.parent / "public" / "data" / "districts.geojson"
ALIASES = HERE / "district_aliases.csv"
FUZZY_CUTOFF = 0.8
# Words that distinguish sibling districts; a fuzzy match must not change them.
DIRECTIONAL = {"east", "west", "north", "south", "central", "upper", "lower", "purba", "paschim", "uttar",
               "dakshin", "urban", "rural", "new", "old", "sri", "city"}

STATE_ALIASES = {
    "orissa": "Odisha", "uttaranchal": "Uttarakhand", "pondicherry": "Puducherry",
    "nct of delhi": "Delhi", "delhi nct": "Delhi", "national capital territory of delhi": "Delhi",
    "andaman and nicobar": "Andaman and Nicobar Islands", "andaman nicobar islands": "Andaman and Nicobar Islands",
    "dadra and nagar haveli": "Dadra and Nagar Haveli and Daman and Diu",
    "daman and diu": "Dadra and Nagar Haveli and Daman and Diu",
    "dadra nagar haveli and daman diu": "Dadra and Nagar Haveli and Daman and Diu",
    "jammu kashmir": "Jammu and Kashmir",
}


def norm(s: str) -> str:
    s = s.lower().replace("&", " and ")
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\b(district|dist|zila)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def key(s: str) -> str:
    """Spacing/punctuation-insensitive key: 'S.A.S. Nagar' == 'SAS Nagar', 'Sahib Ganj' == 'Sahibganj'."""
    return norm(s).replace(" ", "")


class Matcher:
    def __init__(self) -> None:
        self.by_state: dict[str, dict[str, dict]] = {}
        self.states: dict[str, str] = {}  # normalized -> canonical state name
        for f in json.loads(GEOJSON.read_text())["features"]:
            p = f["properties"]
            self.states[norm(p["state"])] = p["state"]
            self.by_state.setdefault(p["state"], {})[key(p["name"])] = p
        # (state, wris_name) -> (geojson state, geojson name). geojson_state is optional: blank means
        # the same state; set it where WRIS files a district under the wrong state (MP / Rajnandgaon).
        self.aliases: dict[tuple[str, str], tuple[str, str]] = {}
        if ALIASES.exists():
            with open(ALIASES, newline="", encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    self.aliases[(norm(r["state"]), key(r["wris_name"]))] = (r.get("geojson_state") or r["state"], r["geojson_name"])

    def state(self, name: str) -> str | None:
        n = norm(name)
        if n in STATE_ALIASES:
            return STATE_ALIASES[n]
        return self.states.get(n)

    def match(self, state: str, district: str) -> tuple[dict | None, str]:
        st = self.state(state)
        if st is None:
            return None, "none:state"
        pool = self.by_state[st]
        alias = self.aliases.get((norm(st), key(district)))
        if alias is not None:
            alias_state = self.state(alias[0])
            p = self.by_state[alias_state].get(key(alias[1])) if alias_state else None
            return (p, "alias") if p else (None, "none:bad-alias")
        if key(district) in pool:
            return pool[key(district)], "exact"
        want = DIRECTIONAL & set(norm(district).split())
        for k in difflib.get_close_matches(key(district), list(pool), n=3, cutoff=FUZZY_CUTOFF):
            if DIRECTIONAL & set(norm(pool[k]["name"]).split()) == want:
                return pool[k], "fuzzy"
        return None, "none"


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "targets.csv"
    m = Matcher()
    rows, counts = [], {}
    seen = set()
    with open(src, newline="") as fh:
        for r in csv.DictReader(fh):
            k = (r["state"], r["district"])
            if k in seen:
                continue
            seen.add(k)
            p, how = m.match(*k)
            counts[how.split(":")[0]] = counts.get(how.split(":")[0], 0) + 1
            rows.append({"wris_state": k[0], "wris_district": k[1], "method": how,
                         "id": p["id"] if p else "", "state": p["state"] if p else "", "name": p["name"] if p else ""})
    out = HERE / "district_crosswalk.csv"
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["wris_state"])
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} WRIS districts -> {out.name}: {counts}")
    for r in rows:
        if r["method"] == "fuzzy":
            print(f"  review fuzzy: {r['wris_state']} / {r['wris_district']} -> {r['name']}")
    for r in rows:
        if r["method"].startswith("none"):
            print(f"  UNMATCHED: {r['wris_state']} / {r['wris_district']} ({r['method']})")
    matched = {r["id"] for r in rows if r["id"]}
    missing = [(s, p["name"]) for s, pool in m.by_state.items() for p in pool.values() if p["id"] not in matched]
    print(f"{len(missing)} geojson districts have no WRIS counterpart (fine if WRIS has no stations there)")


if __name__ == "__main__":
    main()

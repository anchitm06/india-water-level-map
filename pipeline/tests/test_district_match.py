"""Run: python3 -I pipeline/tests/test_district_match.py  (pytest also works)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import district_match as dm  # noqa: E402

M = dm.Matcher()


def test_every_alias_targets_a_real_district():
    for (st, wris), (target_state, target) in M.aliases.items():
        assert M.state(target_state), (st, wris, target_state)
        assert dm.key(target) in M.by_state[M.state(target_state)], (st, wris, target)


def test_cases():
    cases = [
        ("Haryana", "Gurgaon", "Gurugram", "alias"),
        ("Orissa", "Keonjhar", "Kendujhar", "alias"),
        ("Uttar Pradesh", "ALLAHABAD", "Prayagraj", "alias"),
        ("Delhi", "EAST", "Delhi", "alias"),
        ("NCT of Delhi", "North West", "Delhi", "alias"),
        ("Punjab", "S.A.S Nagar", "S.A.S. Nagar", "alias"),
        ("Jharkhand", "Sahib Ganj", "Sahibganj", "exact"),
        ("Jammu & Kashmir", "Srinagar District", "Srinagar", "exact"),
        ("Uttarakhand", "Dehradoon", "Dehradun", "fuzzy"),
        ("Telangana", "Hyderabad", "Hyderabad", "exact"),
        # real WRIS names that failed the first match run (2026-10-28)
        ("Madhya Pradesh", "EAST NIMAR", "Khandwa", "alias"),
        ("Telangana", "JOGULAMBA(GADWAL)", "Jogulamba Gadwal", "alias"),
        ("West Bengal", "East Medinipur", "Purba Medinipur", "alias"),
        ("Madhya Pradesh", "Rajnandgaon", "Rajnandgaon", "alias"),  # filed under the wrong state
        ("Gujarat", "DAMAN", "Daman", "alias"),
    ]
    for st, d, name, how in cases:
        p, h = M.match(st, d)
        assert p and p["name"] == name and h == how, (st, d, p, h)


def test_no_cross_state_or_garbage():
    assert M.match("Haryana", "Mysore")[0] is None
    assert M.match("Bihar", "East Champaran")[1] == "exact"
    assert M.match("Bihar", "Pashchim Champaran")[0]["name"] == "West Champaran"  # alias, not fuzzy
    p, how = M.match("West Bengal", "Purba Medinpur")  # typo must not flip to Paschim
    assert p is None or p["name"] == "Purba Medinipur"
    assert M.match("Atlantis", "Foo")[0] is None
    # undivided districts, split since, deliberately have no alias (aggregate.py uses lat/lon)
    assert M.match("West Bengal", "BARDDHAMAN")[0] is None
    assert M.match("West Bengal", "Mednipur")[0] is None


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)

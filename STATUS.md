# Project status and plan (handoff notes)

Last updated: 2026-10-27 (second session). Branch: `claude/india-groundwater-map-znsfiw`.

## Goal
Static GitHub Pages site: interactive India map, **district level**, groundwater depth (m below
ground level), pre/post-monsoon, historical + latest data, per-district history chart, CSV export.

## Decisions made
- District granularity; hosting on GitHub Pages; fetch data from the India-WRIS API.
- No backend: pipeline pre-aggregates to static JSON in `public/data/`.

## Done
- Frontend (Vite + TS + MapLibre + Chart.js) in `src/`, `index.html`: choropleth, season select,
  year slider + play, legend, click panel with chart, CSV download. Built and checked in headless
  Chromium; no console errors.
- `.github/workflows/deploy.yml`: GitHub Pages deploy on push to `main` (not yet run; Pages source
  must be set to "GitHub Actions" in repo settings).
- `pipeline/generate_placeholder.py`: writes **synthetic** `public/data/districts.geojson` (1° grid,
  not real districts) and `levels.json` (random). UI shows a yellow banner while
  `meta.placeholder` is true.
- `pipeline/fetch.py`: India-WRIS downloader written from the swagger
  (`POST /Dataset/Ground Water Level`, params stateName, districtName, agencyName, startdate,
  enddate, download, page, size<=1000). Seasonal windows only, daily-median reduction, resumable.
  Tested only on `pipeline/tests/sample_gwl.json` (run `python3 -I -c` as in tests; pytest not installed).
- `pipeline/aggregate.py`: station readings -> district x year x season medians via point-in-polygon
  (shapely). Written, **untested on real data**.

- `pipeline/build_districts.py`: real district boundaries (724 features, ids `stcode-dtcode`, ~340 KB)
  from udit-001/india-maps-data on GitHub (Census 2011 + later splits, newest-first so e.g.
  Telangana's 31 districts replace parents). `public/data/districts.geojson` is now REAL;
  `generate_placeholder.py --keep-districts` writes random `levels.json` keyed to them (banner
  still shown). Verified rendering in headless Chromium. Caveat: boundaries are a mixed-vintage
  patchwork and not authoritative; the J&K/Ladakh/Arunachal outline needs a compliance check vs
  Survey of India before launch. India-WRIS district names must be matched to these (state, name).

- `pipeline/district_match.py` + `district_aliases.csv` + `tests/test_district_match.py`: crosswalk
  from India-WRIS (state, district) names to geojson ids. Order: alias -> exact (punctuation/spacing
  insensitive) -> fuzzy (same state, never flips East/West/Purba/Paschim etc.) -> none. State aliases
  (Orissa, NCT of Delhi, `&`, Dadra/Daman merge) built in. All Delhi WRIS districts map to the single
  `Delhi` polygon. Writes `pipeline/district_crosswalk.csv`. The ~100 aliases are from my knowledge of
  renames, NOT yet checked against real WRIS names: after the first fetch run
  `python pipeline/district_match.py` (reads `targets.csv`), review the `fuzzy` and `UNMATCHED` lines,
  and add rows to the alias CSV. Note `aggregate.py` assigns by lat/lon, so names only matter for
  building `targets.csv` and sanity checks.

## Blocked / not verified
- **The Claude cloud sandbox could not reach `indiawris.gov.in`, `data.gov.in`, `cgwb.gov.in`.**
  First a 403 from the egress policy; after "full access" was enabled the proxy let the CONNECT
  through but the tunnel was reset/closed mid-exchange (`ws_closed_mid_exchange`), which looks like
  the sites refusing this server's IPs. Do NOT spoof a browser user-agent to get around it (the
  sandbox classifier denied that, and it is bot-protection circumvention).
- Request bodies for the master endpoints (`/masterState/StateList`,
  `/masterDistrict/getDistrictbyState`, `/masterAgency/districAgencyList`) are not in the swagger
  text. `python pipeline/fetch.py --discover` makes a best-effort call; may need a body copied from
  the browser network tab.
- Assumption to verify: `dataValue` (unit "m", datatypeCode GGZ) = depth below ground level.
  Sample range 0.0-4.86 m; exact 0.0 values may be sensor artefacts (not filtered yet).
- India-WRIS / data.gov.in still unreachable from the sandbox on 2026-10-27 (connection reset);
  `fetch.py` remains untested against the live API. Run it locally.

- Tried a GitHub Actions runner (Azure US IP) on 2026-10-27: `indiawris.gov.in` and `data.gov.in` both
  timed out / refused to connect, so hosted runners are blocked too (probably geo/IP filtering of
  non-Indian ranges). The probe workflow was removed; see git history (commit "Add workflow to probe
  India-WRIS...") if you want to re-run it. Remaining options: run `fetch.py` from an Indian-IP machine
  (local, or a self-hosted runner there), or request the data officially from CGWB/India-WRIS.
- The Pages deploy run on `main` failed on 2026-10-27 (run 40573852076); not yet investigated.

## Next steps
1. In a new session, first test reachability: `curl -sS -m 20 -o /dev/null -w "%{http_code}\n" https://indiawris.gov.in/`
   and `curl -sS "$HTTPS_PROXY/__agentproxy/status"` (check `recentRelayFailures`). If still
   reset, run the fetch locally instead.
2. If reachable: `--discover`, build `pipeline/targets.csv` (state,district,agency), run `fetch.py`
   (test one district first), confirm what `dataValue` means, check 0.0 handling.
3. (Boundaries and matcher done, see above.) Still: sensitive-border compliance check, and tuning
   the alias table against real WRIS names.
4. Run `aggregate.py`, validate against published CGWB figures, replace the placeholder data,
   remove the placeholder banner logic dependence.
5. Polish: station layer, district search, latest-vs-previous trend, mobile/accessibility checks,
   source and caveat notes in the UI.
6. Scheduled refresh via GitHub Actions (only if the API is reachable from GitHub runners), enable
   Pages, optionally open a PR to `main`.

# Project status and plan (handoff notes)

Last updated: 2026-10-28 (local machine run). Branch: `claude/india-groundwater-map-znsfiw`.

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
- The Pages deploy run on `main` failed on 2026-10-27 (run 40573852076). Investigated 2026-10-28:
  build job and artifact upload succeeded; `actions/deploy-pages@v4` got a 404 creating the
  deployment because **GitHub Pages is not enabled** on the repo (`has_pages: false`). Fix: repo
  Settings -> Pages -> Source: "GitHub Actions", then re-run the workflow. The workflow file itself
  is fine. Only a Node 20 deprecation warning for deploy-pages@v4 (forced to Node 24, still runs).

## Local machine run (2026-10-28, user's Windows PC in India)
- **India-WRIS is reachable from the local machine.** Live
  `fetch_window("Delhi", "East", "Delhi SW GW", ...)` returned real readings in the same shape
  as `sample_gwl.json`. Tests still pass.
- TLS gotcha: Windows `curl` (schannel) refuses the site with `CRYPT_E_REVOKED`. The
  `*.indiawris.gov.in` cert (eMudhra, valid Oct 6 to Dec 18 2026) is reported revoked. Python
  (OpenSSL) validates the chain and hostname but does not check revocation, so `fetch.py` works.
  Use Python rather than curl on Windows.
- Master endpoints (not in the swagger) that work, found by trial:
  `POST /masterState/StateList` body `{"datasetcode":"GWATERLVL"}` (32 states, with `statecode`);
  `POST /masterDistrict/getDistrictbyState` body `{"datasetcode":"GWATERLVL","statecode":"45"}`
  (gives `districtname`, uppercase, and `district_id`);
  `POST /masterAgency/AgencyListInAnyCase` body `{"datasetcode":"GWATERLVL","district_id":107102}`
  (taken from the site's own request; tahsil/block fields are optional). `--discover` chains all
  three and prints the full `state,district,agency` CSV for `targets.csv`.
- `agencyName` is required (missing = 400, blank = 0 rows). CGWB is spelled `CGWB`. An earlier
  10-day March window simply had no CGWB readings; full seasons do.
- **dataValue sign is inconsistent.** CGWB Delhi East, post-monsoon 2023, 7 telemetric stations:
  most report depth as negative (-3 to -27 m), two as positive (25.85, 14.9 m). `-1000` is a no-data
  sentinel (CGWBDL46). AAXI014 jumps to ~44 m in a 45 m well (dry or sensor at the bottom).
  CGWBDL46 is a faulty sensor drifting across hundreds of metres (down to -1124 m) in Mar-May 2023.
  `fetch.clean_level` now takes abs, drops 0.0, >= 200 m, and >= wellDepth. Still to do: a
  per-station outlier check in `aggregate.py` (a drifting sensor under 200 m would get through)
  and validation against published CGWB district figures. Delhi SW GW returned nothing for
  Oct-Dec 2023.
- `targets.csv` built (1,331 rows, 752 districts, 32 states; CGWB in almost every district plus
  state agencies). Test fetch over 2015/2022/2023 for Delhi East and Ludhiana: CGWB has Manual
  readings (one per station per season) back to at least 2015, with Telemetric readings from about
  2022. Telemetric windows are large (Ludhiana Punjab GW post-2023: 23k raw rows, 60 s), so a full
  run over 1,331 targets x 25 years x 2 seasons will take many hours; it is resumable.
- `pipeline/tests/test_fetch.py` had no `__main__` runner, so `python` on it ran nothing; fixed.
- Matcher on the 740 unique real WRIS names in `targets.csv` (after 30 new aliases, 2026-10-28):
  exact 617, alias 83, fuzzy 38, none 2. The fuzzy matches all look right (spelling variants such
  as Hazaribag/Hazaribagh). `district_aliases.csv` has an optional `geojson_state` column for rows
  WRIS files under the wrong state (MP/Rajnandgaon -> Chhattisgarh, AP/Khammam -> Telangana,
  Gujarat/Daman and Diu -> Dadra and Nagar Haveli and Daman and Diu). Districts newer than the
  boundary set map to their parent: Vijayanagara -> Ballari (2021), Gaurella Pendra Marwahi ->
  Bilaspur (2020). Left unmatched on purpose: West Bengal BARDDHAMAN (split into Purba/Paschim
  Bardhaman, 2017) and undivided Mednipur (split 2002); no single polygon fits, and aggregate.py
  places their stations by lat/lon anyway. Re-run with `python pipeline/district_match.py`.

- Fetch made efficient and gentle (2026-10-28): one Mar-Dec request per year before 2022 (manual
  data), per-season requests from 2022 (telemetric); one shared throttle (max 2 req/s) across
  `--workers` (default 2, max 3); failed windows are skipped and retried next run, 5 failures in a
  row stop the run; `--state` filter; live ETA. WRIS lists 136 districts twice in different case
  and its API ignores case, so targets are de-duplicated (1,331 -> 1,195). Data before ~1985 is a
  handful of wells per district (Pune/Ludhiana/Coimbatore probes), so default `--from-year 1985`.
- **Delhi trial run done** (`--state Delhi`, 15 targets, 1985-2026): 1,260 season windows in 26 min,
  no failures, 37k daily readings in `pipeline/raw/` (gitignored, kept, so the full run skips
  Delhi). Sanity: median depth 4 m (1985) -> 10 m (2015), deepest wells 60-67 m, only 3 readings
  in pre-monsoon 2020 (lockdown). Telemetric years add thousands of readings and a few outliers
  (174 m, 110 m) for the aggregate.py outlier check. Delhi SW GW telemetric data is all 0.0 until
  2024 and gets dropped. Scaling Delhi's rate gives roughly 30-35 h for all 1,195 targets with 2
  workers; the run prints its own ETA.

- `aggregate.py` reworked (2026-10-28), tests in `pipeline/tests/test_aggregate.py`:
  - each station is reduced to one median per (year, season) before the district median, so a
    telemetric station (90 daily readings) no longer outweighs 90 manual wells;
  - outlier check per station, robust (median/MAD with a metre floor): daily spikes vs the
    station's season median (k=5, floor 2 m), and season jumps vs the same station's seasons
    within +-5 years (k=5, floor 15 m, needs 3 neighbours). The local window keeps long declines,
    recoveries and isolated seasons before data gaps;
  - repeated (station, date) rows count once (an interrupted fetch can append a window twice).
  On the Delhi trial data: 310 daily spikes and 13 station-seasons dropped. 11 are clearly bad
  (a batch of unrelated wells all ~44 m in pre-monsoon 2017, 99 m / 73 m spikes, a 10 m value
  among 41-60 m). Two are ambiguous: AAXI014 (15 m in 2023, then 41-44 m in a 45 m well, which looks
  dry/sensor-at-bottom, so the wrong side may be dropped) and DLIF19 (25 m then 6-8 m).
  Delhi `07-000` pre-monsoon: 4.3 (1985), 6.0 (1995), 8.3 (2005), 10.0 (2015) m.
  shapely is installed in the user site-packages, which `python -I` hides: run `aggregate.py`
  without `-I`. Running it while the fetch is going is safe (it only reads readings.csv), but
  restore the placeholder `public/data/levels.json` (`git checkout`) until the fetch is complete.
- Station counts: `levels.json` now has `data[id].stations = {pre: [...], post: [...]}` (stations
  behind each median, 0 when none). The district panel shows them ("2020 Pre-monsoon: 3.9 m bgl
  (3 stations)"), as do the chart tooltips and two extra CSV columns. Optional in the frontend, so
  the placeholder data (no counts) still works. Checked in headless Edge on real Delhi data
  (2015: 104 stations, 2020: 3), no page errors; the chart tooltip text was not checked visually.
  `npm ci` was needed locally before `npm run build`.

## Full fetch and aggregate (2026-10-30)
- Full fetch done: all 100,380 windows (19 failed windows fetched on a re-run). 9.07M daily readings,
  65,823 stations (1,290 outside every district polygon), 387 MB `pipeline/raw/readings.csv`.
  Post-monsoon 2026 was fetched while in progress and is marked done: to refresh it, delete the
  `|2026|post` lines from `pipeline/raw/done.log` and re-run `fetch.py`.
- aggregate.py streams the file (peak < 1 GB; the list-based version risked running out of
  memory with ~4 GB free). Cleaning: 147k daily spikes, 5,187 station-season jumps dropped.
- **Network change problem found and fixed.** Plain district medians made the typical district
  ~2.5 m deeper 2015 -> 2024 (pre), but the 5,541 stations measured in both years changed only
  0.2 m. Cause: in 2024 only ~9% of stations are CGWB manual wells (median 5.3 m); the rest are
  telemetric/state wells tapping deeper water (median 13 m). Now `district_series` chain-links
  each district over stations measured in both years and pins each run to CGWB manual wells
  (15-digit lat/lon IDs, `is_manual`); a run with no manual wells continues from the previous
  run's level if within 5 years, else uses its own median; both flagged `mixed` and shown in the
  panel as "estimated, no manual wells". Result, 2015 -> 2024 pre median change: 0.33 m in
  manual-pinned districts (409), 0.23 m in mixed ones (142). The 2024 map now matches the 2015
  pattern with deepening in the north-west. ASSUMPTION: 15-digit numeric IDs = CGWB manual network.
- Real `public/data/levels.json` committed 2026-10-30 (replaces the placeholder; banner hidden).
  Regenerate with `python pipeline/aggregate.py` after any new fetch.

## District detail view (2026-10-30)
- Full-page view per district at `#district=<id>` (shareable), opened from the panel's "Open
  detailed view"; Back returns to the map with the season/year chosen there. Code: `src/detail.ts`
  (page, station map, charts), `src/stats.ts` (trend = least-squares slope, 10-year trend, change vs
  ~10 years earlier, monsoon recharge = median pre-post of the same year over the last 10 years,
  rank within the state, deepest/shallowest year), `src/shared.ts` (types, colours).
- Station map: `aggregate.py` now also writes `public/data/stations/<id>.json` (650 files, 19 MB,
  largest 160 KB; sparse per-station seasonal values after cleaning), loaded on demand. Wells are
  coloured by depth for the chosen year (grey = not measured), dark outline = CGWB manual well;
  click a well for its own chart. Committed, since CI cannot fetch India-WRIS; each regenerate
  rewrites these files, so the repo grows by up to ~19 MB per data refresh.
- Checked in headless Edge (desktop and 390 px): direct link, panel button, well click, Back, no
  horizontal overflow, no console errors (a favicon 404 fixed with an inline icon). Ludhiana:
  22.1 m pre-monsoon 2026, 0.40 m/year deeper long-term, post-monsoon deeper than pre-monsoon.

## CGWB check (2026-10-30)
- Reference: CGWB Ground Water Year Book 2023-24 (cgwb.gov.in, reachable from the local machine),
  annexures 1 and 3: per state, % of manual-network wells in each depth band for pre-monsoon (May)
  and November 2023. Script: `python pipeline/validate_cgwb.py <pdf> --year 2023`.
- **Pre-monsoon 2023 agrees well.** Over the 25 states with data on both sides, % per band
  CGWB 6.6 / 33.5 / 40.7 / 14.8 / 2.8 / 1.7 vs ours 6.0 / 31.1 / 40.0 / 16.8 / 4.2 / 1.8
  (15,565 vs 13,088 wells); median band agrees in 22/25 states; big states within 1-4 points
  (Kerala 0.8, Odisha 1.1, MP 1.7, Karnataka 2.0, Chhattisgarh 2.5, Maharashtra 3.9, Rajasthan 4.6).
- **Gaps are in India-WRIS, not the pipeline:** WRIS has no CGWB manual readings for Haryana, Punjab,
  Delhi, HP in pre-monsoon 2023 and only 8 for UP; those districts rely on telemetric/state wells
  (flagged "estimated"). November 2023 manual data is mostly missing from WRIS (about 4,400 manual
  wells vs ~15,000 in Nov 2021/2022; none for Indore, Thrissur, Anand when queried live), so
  post-monsoon from 2023 is thin. West Bengal, Telangana, AP, Tamil Nadu have more lat/lon-coded
  manual wells than CGWB lists (state agencies use the same codes) and differ by 10-18 points.
- **Bug found and fixed: "manual" was decided by station ID** (15-digit lat/lon code), but CGWB and
  West Bengal telemetric wells use those codes too (checked live: Bankura CGWB, 152 of 154 stations
  coded, mostly telemetric). Now a station-season is manual only if it has a lat/lon code AND <= 3
  reading days in the season. Tried frequency alone first: it pulled in ~6,000 Rajasthan state wells
  (deeper network) and made districts jump between runs (Karauli 11.7 -> 26.6 m 1995-2005).
  A year also pins a run only if its manual wells are >= 3 and >= half of its stations (three sparse
  telemetric wells among 25 had pinned Delhi 2023-26 at 2.1 m). Result vs the previously published
  data: 85% of values unchanged, 848 of 47,173 moved > 5 m (mostly Rajasthan, UP, Tamil Nadu,
  Haryana); 2015 -> 2024 median change 0.30 m (manual-pinned) and 0.27 m (estimated) districts.

## Next steps
1. Merge the corrected data to `main` so the live site picks it up.
2. (Aliases done, see above.)
3. (Boundaries and matcher done, see above.) Still: sensitive-border compliance check.
4. Run `aggregate.py`, validate against published CGWB figures, replace the placeholder data,
   remove the placeholder banner logic dependence.
5. Polish: station layer, district search, latest-vs-previous trend, mobile/accessibility checks,
   source and caveat notes in the UI.
6. Scheduled refresh via GitHub Actions (only if the API is reachable from GitHub runners), enable
   Pages, optionally open a PR to `main`.

"""Download raw station water-level readings from India-WRIS into pipeline/raw/.

Not implemented yet: the environment could not reach indiawris.gov.in when this was
scaffolded, so the real endpoints and response format are still unverified. Once the
host is reachable, inspect the site's network calls, check its terms of use, then
write readings to pipeline/raw/readings.csv with the columns aggregate.py expects:

    station_id,lat,lon,date,level_m_bgl
"""
raise SystemExit("fetch.py is not implemented yet - see the module docstring")

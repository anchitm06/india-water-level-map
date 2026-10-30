import maplibregl from "maplibre-gl";
import { Chart } from "chart.js/auto";
import { $, base, colorFor, NO_DATA, SEASON_LABEL, SEASONS, stationsText, wellName, type Levels, type Season, type Station } from "./shared";
import { districtStats } from "./stats";

const ordinal = (n: number) => {
  const sfx = ["th", "st", "nd", "rd"], v = n % 100;
  return n + (sfx[(v - 20) % 10] ?? sfx[v] ?? sfx[0]); // 1st 2nd 3rd 4th ... 11th 12th 13th ... 21st
};
const change = (d: number) => `${Math.abs(d).toFixed(2)} m ${d > 0 ? "deeper" : "shallower"}`;
const rate = (r: number | null) => r == null ? "not enough data" : `${Math.abs(r).toFixed(2)} m/year ${r > 0 ? "deeper" : "shallower"}`;

function bbox(geom: any): [[number, number], [number, number]] {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  const walk = (c: any) => {
    if (typeof c[0] === "number") { x0 = Math.min(x0, c[0]); y0 = Math.min(y0, c[1]); x1 = Math.max(x1, c[0]); y1 = Math.max(y1, c[1]); }
    else c.forEach(walk);
  };
  walk(geom.coordinates);
  return [[x0, y0], [x1, y1]];
}

/** Full-page view of one district: summary stats, a map of its wells, district and well charts. */
export function createDetailView(gj: any, levels: Levels, onClose: (season: Season, yearIdx: number) => void) {
  const stateOf: Record<string, string> = Object.fromEntries(gj.features.map((f: any) => [f.properties.id, f.properties.state]));
  const seasonEl = $<HTMLSelectElement>("p-season"), yearEl = $<HTMLSelectElement>("p-year");
  yearEl.innerHTML = levels.years.map((y, i) => `<option value="${i}">${y}</option>`).join("");
  const cache = new Map<string, Promise<Station[]>>();
  const pageTitle = document.title;
  let map: maplibregl.Map | null = null;
  let charts: Chart[] = [];
  let wellChart: Chart | null = null;
  let current: { id: string; feature: any; stations: Station[] } | null = null;

  const season = () => seasonEl.value as Season;
  const yearIdx = () => Number(yearEl.value);
  const loadStations = (id: string) => {
    if (!cache.has(id)) {
      // no file = no wells (404 on Pages; dev/preview servers answer with index.html instead)
      cache.set(id, fetch(`${base}data/stations/${id}.json`).then((r) => (r.ok ? r.json() : { stations: [] }))
        .then((j) => j.stations ?? [], () => []));
    }
    return cache.get(id)!;
  };

  function renderStats() {
    const { id, feature } = current!;
    const series = levels.data[id];
    const s = districtStats(levels, series, feature.properties.state, stateOf, season(), yearIdx());
    const y = levels.years[yearIdx()], v = series[season()][yearIdx()];
    const n = series.stations?.[season()][yearIdx()];
    const est = series.mixed?.[season()][yearIdx()] ? " · estimated, no manual wells" : "";
    const cards: [string, string, string?][] = [
      [`${SEASON_LABEL[season()]} ${y}`, v == null ? "no data" : `${v.toFixed(1)} m`, v == null ? "" : `below ground${stationsText(n)}${est}`],
      ["Long-term trend", rate(s.trend), `${SEASON_LABEL[season()].toLowerCase()}, whole record`],
      ["Last 10 years", rate(s.trend10), `${levels.years[Math.max(0, yearIdx() - 9)]}–${y}`],
      [s.change10 ? `Change since ${s.change10.from}` : "Change over 10 years", s.change10 ? change(s.change10.delta) : "not enough data"],
      ["Monsoon recharge", s.recharge == null ? "not enough data" : `${s.recharge >= 0 ? "rises" : "falls"} ${Math.abs(s.recharge).toFixed(1)} m`,
        s.recharge != null && s.recharge < 0 ? "post-monsoon deeper than pre-monsoon (typical, last 10 years)" : "typical pre- to post-monsoon change, last 10 years"],
      [`Rank in ${feature.properties.state}`, !s.rank ? "no data" : s.rank.of < 2 ? "only district with data" : `${ordinal(s.rank.rank)} deepest of ${s.rank.of}`,
        s.rank ? `${SEASON_LABEL[season()].toLowerCase()} ${y}` : ""],
      ["Deepest / shallowest", s.extremes ? `${s.extremes.deepest[1].toFixed(1)} / ${s.extremes.shallowest[1].toFixed(1)} m` : "no data",
        s.extremes ? `in ${s.extremes.deepest[0]} / ${s.extremes.shallowest[0]}` : ""],
    ];
    const box = $("p-stats");
    box.replaceChildren(...cards.map(([title, value, sub]) => {
      const d = document.createElement("div");
      d.className = "stat";
      d.innerHTML = "<span></span><strong></strong><small></small>";
      d.children[0].textContent = title; d.children[1].textContent = value; d.children[2].textContent = sub ?? "";
      return d;
    }));
  }

  function renderDistrictChart() {
    const series = levels.data[current!.id];
    charts.forEach((c) => c.destroy());
    charts = [new Chart($<HTMLCanvasElement>("p-chart"), {
      type: "line",
      data: {
        labels: levels.years,
        datasets: SEASONS.map((s) => ({
          label: SEASON_LABEL[s], data: series[s], spanGaps: false, pointRadius: 2,
          borderColor: s === "pre" ? "#d2793a" : "#1f5fa8", tension: 0.2,
        })),
      },
      options: {
        maintainAspectRatio: false,
        scales: { y: { reverse: true, title: { display: true, text: "m below ground" } } },
        plugins: {
          legend: { position: "bottom" },
          tooltip: { callbacks: { afterLabel: (c) => stationsText(series.stations?.[SEASONS[c.datasetIndex]][c.dataIndex]).trim() } },
        },
      },
    })];
  }

  function showWell(st: Station | null) {
    wellChart?.destroy();
    wellChart = null;
    if (!st) {
      $("p-well-title").textContent = "Click a well on the map to see its history";
      $("p-well-sub").textContent = "";
      return;
    }
    $("p-well-title").textContent = wellName(st);
    const where = st.place && st.km != null && st.km >= 0.5 ? `${st.km} km from ${st.place} · ` : "";
    $("p-well-sub").textContent = `${where}${st.manual ? "read by hand" : "automatic sensor"} · station ${st.id}`;
    wellChart = new Chart($<HTMLCanvasElement>("p-well-chart"), {
      type: "line",
      data: {
        labels: levels.years,
        datasets: SEASONS.map((s) => ({
          label: SEASON_LABEL[s], data: levels.years.map((y) => st[s][String(y)] ?? null), spanGaps: true, pointRadius: 2,
          borderColor: s === "pre" ? "#d2793a" : "#1f5fa8", tension: 0.2,
        })),
      },
      options: { maintainAspectRatio: false, scales: { y: { reverse: true, title: { display: true, text: "m below ground" } } }, plugins: { legend: { position: "bottom" } } },
    });
  }

  function stationFeatures() {
    const y = String(levels.years[yearIdx()]);
    return {
      type: "FeatureCollection",
      features: current!.stations.map((st) => {
        const v = st[season()][y] ?? null;
        return { type: "Feature", geometry: { type: "Point", coordinates: [st.lon, st.lat] },
                 properties: { id: st.id, has: v != null, color: v == null ? NO_DATA : colorFor(v), manual: st.manual,
                               label: `${wellName(st)}: ${v == null ? "not measured" : `${v.toFixed(1)} m`}` } };
      }),
    };
  }

  function renderMap() {
    const { feature, stations } = current!;
    const measured = stations.filter((st) => st[season()][String(levels.years[yearIdx()])] != null).length;
    $("p-map-note").textContent = stations.length
      ? `${stations.length} wells on record, ${measured} measured in ${SEASON_LABEL[season()].toLowerCase()} ${levels.years[yearIdx()]} (coloured by depth; grey = not measured that year). Dark outline = well read by hand. Hover a well for its location, click for its history.`
      : "No well data for this district.";
    const district = { type: "FeatureCollection", features: [feature] };
    const apply = () => {
      (map!.getSource("district") as maplibregl.GeoJSONSource).setData(district as any);
      (map!.getSource("wells") as maplibregl.GeoJSONSource).setData(stationFeatures() as any);
    };
    if (!map) {
      map = new maplibregl.Map({
        container: "p-map",
        style: { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": "#eef2f5" } }] },
        bounds: bbox(feature.geometry), fitBoundsOptions: { padding: 24 },
        attributionControl: { customAttribution: 'Place names: <a href="https://www.geonames.org/">GeoNames</a> (CC BY 4.0)' },
      });
      const hover = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 8 });
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }));
      map.on("load", () => {
        map!.addSource("district", { type: "geojson", data: district as any });
        map!.addSource("wells", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        map!.addLayer({ id: "d-fill", type: "fill", source: "district", paint: { "fill-color": "#ffffff", "fill-opacity": 0.6 } });
        map!.addLayer({ id: "d-line", type: "line", source: "district", paint: { "line-color": "#1b1f24", "line-width": 1.5 } });
        map!.addLayer({
          id: "wells", type: "circle", source: "wells",
          paint: {
            "circle-color": ["get", "color"], "circle-radius": ["case", ["get", "has"], 5.5, 3],
            "circle-stroke-color": ["case", ["get", "manual"], "#1b1f24", "#ffffff"], "circle-stroke-width": 1,
          },
        });
        map!.on("click", "wells", (e) => showWell(current!.stations.find((s) => s.id === e.features![0].properties!.id) ?? null));
        map!.on("mousemove", "wells", (e) => {
          map!.getCanvas().style.cursor = "pointer";
          const f = e.features![0];
          hover.setLngLat((f.geometry as any).coordinates).setText(f.properties!.label).addTo(map!);
        });
        map!.on("mouseleave", "wells", () => { map!.getCanvas().style.cursor = ""; hover.remove(); });
        apply();
      });
    } else {
      map.resize();
      map.fitBounds(bbox(feature.geometry), { padding: 24, animate: false });
      if (map.isStyleLoaded()) apply(); else map.once("load", apply);
    }
  }

  function refresh() { renderStats(); renderMap(); }
  seasonEl.addEventListener("change", refresh);
  yearEl.addEventListener("change", refresh);
  $("p-back").addEventListener("click", () => { location.hash = ""; });

  return {
    async open(id: string, s: Season, yi: number) {
      const feature = gj.features.find((f: any) => f.properties.id === id);
      if (!feature || !levels.data[id]) return;
      seasonEl.value = s; yearEl.value = String(yi);
      $("p-name").textContent = feature.properties.name;
      $("p-sub").textContent = `${feature.properties.state} · district ${id}`;
      $("page").hidden = false;
      document.title = `${feature.properties.name} · ${pageTitle}`;
      current = { id, feature, stations: [] };
      renderStats(); renderDistrictChart(); showWell(null);
      const stations = await loadStations(id);
      if (current?.id !== id) return; // another district was opened meanwhile
      current.stations = stations;
      renderMap();
    },
    close() {
      if ($("page").hidden) return;
      $("page").hidden = true;
      document.title = pageTitle;
      onClose(season(), yearIdx());
    },
  };
}

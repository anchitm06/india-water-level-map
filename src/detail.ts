import maplibregl from "maplibre-gl";
import { $, bbox, colorFor, loadStations, nearText, SEASON_LABEL, SEASONS, stationsText, token, wellName, type Levels, type Season, type Station } from "./shared";
import { districtStats } from "./stats";
import { Chart, lineOptions, lineSet, stationsTooltip } from "./charts";

const ordinal = (n: number) => {
  const sfx = ["th", "st", "nd", "rd"], v = n % 100;
  return n + (sfx[(v - 20) % 10] ?? sfx[v] ?? sfx[0]); // 1st 2nd 3rd 4th ... 11th 12th 13th ... 21st
};
const short = (s: string, n = 48) => (s.length > n ? s.slice(0, n - 1).trimEnd() + "…" : s); // hover labels; WRIS names reach 86 chars
const change = (d: number) => `${Math.abs(d).toFixed(2)} m ${d > 0 ? "deeper" : "shallower"}`;
const rate = (r: number | null) => r == null ? "not enough data" : `${Math.abs(r).toFixed(2)} m/year ${r > 0 ? "deeper" : "shallower"}`;

/** Full-page view of one district: summary stats, a map of its wells, district and well charts. */
export function createDetailView(gj: any, levels: Levels, onClose: (season: Season, yearIdx: number) => void) {
  const stateOf: Record<string, string> = Object.fromEntries(gj.features.map((f: any) => [f.properties.id, f.properties.state]));
  const seasonEl = $<HTMLSelectElement>("p-season"), yearEl = $<HTMLSelectElement>("p-year");
  yearEl.innerHTML = levels.years.map((y, i) => `<option value="${i}">${y}</option>`).join("");
  const pageTitle = document.title;
  let map: maplibregl.Map | null = null;
  let wellsMoved = false;
  let charts: Chart[] = [];
  let wellChart: Chart | null = null;
  let current: { id: string; feature: any; stations: Station[] } | null = null;

  const season = () => seasonEl.value as Season;
  const yearIdx = () => Number(yearEl.value);

  function renderStats() {
    const { id, feature } = current!;
    const series = levels.data[id];
    const s = districtStats(levels, series, feature.properties.state, stateOf, season(), yearIdx());
    const y = levels.years[yearIdx()], v = series[season()][yearIdx()];
    const n = series.stations?.[season()][yearIdx()];
    const est = series.mixed?.[season()][yearIdx()] ? ". Estimated: no manual wells this year" : "";
    // The level leads as a figure; the other six sit in ruled columns beside it (a <dl>)
    const lead: [string, string, string] = [`${SEASON_LABEL[season()]} ${y}`, v == null ? "No data" : `${v.toFixed(1)} m`,
      v == null ? "" : `below ground${stationsText(n)}${est}`];
    const figures: [string, string, string?][] = [
      ["Long-term trend", rate(s.trend), `${SEASON_LABEL[season()].toLowerCase()}, whole record`],
      ["Last 10 years", rate(s.trend10), `${levels.years[Math.max(0, yearIdx() - 9)]} to ${y}`],
      [s.change10 ? `Change since ${s.change10.from}` : "Change over 10 years", s.change10 ? change(s.change10.delta) : "not enough data"],
      ["Monsoon recharge", s.recharge == null ? "not enough data" : `${s.recharge >= 0 ? "rises" : "falls"} ${Math.abs(s.recharge).toFixed(1)} m`,
        s.recharge != null && s.recharge < 0 ? "post-monsoon deeper than pre-monsoon (typical, last 10 years)" : "typical pre- to post-monsoon change, last 10 years"],
      [`Rank in ${feature.properties.state}`, !s.rank ? "no data" : s.rank.of < 2 ? "only district with data" : `${ordinal(s.rank.rank)} deepest of ${s.rank.of}`,
        s.rank ? `${SEASON_LABEL[season()].toLowerCase()} ${y}` : ""],
      ["Deepest and shallowest", s.extremes ? `${s.extremes.deepest[1].toFixed(1)} and ${s.extremes.shallowest[1].toFixed(1)} m` : "no data",
        s.extremes ? `in ${s.extremes.deepest[0]} and ${s.extremes.shallowest[0]}` : ""],
    ];
    const leadEl = document.createElement("div");
    leadEl.className = "lead";
    leadEl.innerHTML = '<span class="label"></span><span class="figure"></span><span class="sub"></span>';
    lead.forEach((t, i) => { leadEl.children[i].textContent = t; });
    const dl = document.createElement("dl");
    for (const [title, value, sub] of figures) {
      const d = document.createElement("div");
      d.innerHTML = "<dt></dt><dd></dd>";
      d.children[0].textContent = title;
      d.children[1].textContent = value;
      if (sub) d.children[1].insertAdjacentHTML("beforeend", "<small></small>"), (d.children[1].lastElementChild as HTMLElement).textContent = sub;
      dl.append(d);
    }
    $("p-stats").replaceChildren(leadEl, dl);
  }

  function renderDistrictChart() {
    const series = levels.data[current!.id];
    charts.forEach((c) => c.destroy());
    charts = [new Chart($<HTMLCanvasElement>("p-chart"), {
      type: "line",
      data: { labels: levels.years, datasets: SEASONS.map((s) => lineSet(s, series[s], false)) },
      options: lineOptions(stationsTooltip(series.stations, SEASONS)),
    })];
  }

  function showWell(st: Station | null) {
    wellChart?.destroy();
    wellChart = null;
    $("p-well-box").hidden = !st; // no empty chart frame before a well is picked
    $("p-well-title").classList.toggle("empty", !st); // the prompt reads as a hint, not a heading
    if (!st) {
      $("p-well-title").textContent = "Click a well on the map to see its history";
      $("p-well-sub").textContent = "";
      return;
    }
    $("p-well-title").textContent = wellName(st);
    // GeoNames location as the subtitle when the title is the WRIS name, else just its distance
    const where = st.name ? `${nearText(st)}. ` : st.place && st.km != null && st.km >= 0.5 ? `${st.km} km from ${st.place}. ` : "";
    $("p-well-sub").textContent = `${where}${st.manual ? "Read by hand" : "Automatic sensor"}, station ${st.id}.`;
    wellChart = new Chart($<HTMLCanvasElement>("p-well-chart"), {
      type: "line",
      data: { labels: levels.years, datasets: SEASONS.map((s) => lineSet(s, levels.years.map((y) => st[s][String(y)] ?? null), true)) },
      options: lineOptions(),
    });
  }

  function stationFeatures() {
    const y = String(levels.years[yearIdx()]);
    return {
      type: "FeatureCollection",
      features: current!.stations.map((st) => {
        const v = st[season()][y] ?? null;
        return { type: "Feature", geometry: { type: "Point", coordinates: [st.lon, st.lat] },
                 properties: { id: st.id, has: v != null, color: v == null ? token("--map-line") : colorFor(v), manual: st.manual,
                               label: `${short(wellName(st))}${st.name && st.place ? ` (near ${st.place})` : ""}: ${v == null ? "not measured" : `${v.toFixed(1)} m`}` } };
      }),
    };
  }

  function renderMap() {
    const { feature, stations } = current!;
    const measured = stations.filter((st) => st[season()][String(levels.years[yearIdx()])] != null).length;
    $("p-map-note").textContent = stations.length
      ? `${stations.length} wells on record, ${measured} measured in ${SEASON_LABEL[season()].toLowerCase()} ${levels.years[yearIdx()]}. Colour is depth; small grey dots were not measured that year; a dark ring marks a well read by hand. Hover a well for its location, click for its history.`
      : "No well data for this district.";
    const district = { type: "FeatureCollection", features: [feature] };
    const apply = () => {
      (map!.getSource("district") as maplibregl.GeoJSONSource).setData(district as any);
      (map!.getSource("wells") as maplibregl.GeoJSONSource).setData(stationFeatures() as any);
    };
    if (!map) {
      map = new maplibregl.Map({
        container: "p-map",
        style: { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": token("--map-ground") } }] },
        bounds: bbox(feature.geometry), fitBoundsOptions: { padding: 24 },
        attributionControl: { customAttribution: 'Place names: <a href="https://www.geonames.org/">GeoNames</a> (CC BY 4.0)' },
      });
      const hover = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 8 });
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }));
      // Re-fit the district when the box resizes (a rotated phone, a resized window) unless the reader moved it
      map.on("movestart", (e) => { if ((e as any).originalEvent) wellsMoved = true; });
      map.on("resize", () => { if (!wellsMoved && current) map!.fitBounds(bbox(current.feature.geometry), { padding: 24, animate: false }); });
      map.on("load", () => {
        map!.addSource("district", { type: "geojson", data: district as any });
        map!.addSource("wells", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        map!.addLayer({ id: "d-fill", type: "fill", source: "district", paint: { "fill-color": token("--color-paper-3"), "fill-opacity": 1 } });
        map!.addLayer({ id: "d-line", type: "line", source: "district", paint: { "line-color": token("--color-ink-2"), "line-width": 1.2 } });
        map!.addLayer({
          id: "wells", type: "circle", source: "wells",
          paint: {
            // measured wells in their depth colour, a dark ring on the hand-read ones; unmeasured ones a quiet grey dot
            "circle-color": ["get", "color"], "circle-radius": ["case", ["get", "has"], 5.5, 3],
            "circle-stroke-color": ["case", ["all", ["get", "has"], ["get", "manual"]], token("--color-ink"), token("--color-muted")],
            "circle-stroke-width": ["case", ["all", ["get", "has"], ["get", "manual"]], 2, ["get", "has"], 0.75, 0],
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
      wellsMoved = false;
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
      $("p-sub").textContent = `${feature.properties.state}, district ${id}`;
      $("page").hidden = false;
      window.scrollTo(0, 0); // the view replaces the map screen, which may have been scrolled on a phone
      document.title = `${feature.properties.name}: ${pageTitle}`;
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

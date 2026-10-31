import maplibregl from "maplibre-gl";
import { $, base, bbox, CLASSES, colorFor, loadStations, noData, SEASONS, stationsText, token, type Levels, type Season } from "./shared";
import { createSearch } from "./search";

// Chart.js and the district view load on first use, so the map's first paint does not wait for them.
const loadCharts = () => import("./charts");

async function main() {
  const [gj, levels] = await Promise.all([
    fetch(`${base}data/districts.geojson`).then((r) => r.json()),
    fetch(`${base}data/levels.json`).then((r) => r.json() as Promise<Levels>),
  ]);
  $("banner").hidden = !levels.meta.placeholder;
  $("method").hidden = levels.meta.placeholder;

  const yearEl = $<HTMLInputElement>("year");
  yearEl.min = "0"; yearEl.max = String(levels.years.length - 1); yearEl.value = yearEl.max;
  const seasonEl = $<HTMLSelectElement>("season");
  let selected: string | null = null;
  let chart: { destroy(): void } | null = null;

  // One stepped bar: each step is labelled by the depth it starts at, "no data" set apart.
  const legend = $("legend");
  let lo = 0;
  for (const [max, c] of CLASSES) {
    legend.insertAdjacentHTML("beforeend", `<div class="step"><i style="background:var(${c})"></i>${max === Infinity ? `${lo}+` : lo}</div>`);
    lo = max;
  }
  legend.insertAdjacentHTML("beforeend", `<div class="none"><i style="background:var(--data-none)"></i>No data</div>`);
  legend.insertAdjacentHTML("beforeend", `<div class="unit">Metres below ground</div>`);

  let hoverId: string | null = null; // district under the mouse; reset on repaint so its popup text updates
  const valueAt = (id: string) => levels.data[id]?.[seasonEl.value as Season]?.[Number(yearEl.value)] ?? null;

  const map = new maplibregl.Map({
    container: "map",
    style: { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": token("--map-ground") } }] },
    bounds: [[67, 6], [98, 38]],
    fitBoundsOptions: { padding: 20 },
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }));
  // Fit once the container has its real size: the constructor's fit can run before layout settles, and
  // a shared #district= link opens with the map screen hidden (zero size) until Back.
  // Until the reader moves the map (or search does), it re-fits India whenever its box changes size.
  let fitted = false, moved = false;
  const fitIndia = () => {
    map.resize();
    if (fitted || !map.getContainer().clientWidth) return;
    map.fitBounds([[68, 6.5], [97.5, 37.2]], { padding: 24, animate: false });
    fitted = true;
  };
  map.on("movestart", (e) => { if ((e as any).originalEvent) moved = true; });
  map.on("resize", () => {
    if (moved || !map.getContainer().clientWidth) return;
    map.fitBounds([[68, 6.5], [97.5, 37.2]], { padding: 24, animate: false });
    fitted = true;
  });

  // One fill expression per season and year, built on first use and reused (Play and the slider revisit them).
  const exprCache = new Map<string, maplibregl.ExpressionSpecification>();
  const fillExpr = () => {
    const key = `${seasonEl.value}|${yearEl.value}`;
    let expr = exprCache.get(key);
    if (!expr) {
      const e: unknown[] = ["match", ["get", "id"]];
      for (const f of gj.features) e.push(f.properties.id, colorFor(valueAt(f.properties.id)));
      e.push(noData());
      exprCache.set(key, (expr = e as maplibregl.ExpressionSpecification));
    }
    return expr;
  };
  const paint = () => {
    hoverId = null;
    $("year-out").textContent = String(levels.years[Number(yearEl.value)]);
    map.setPaintProperty("fill", "fill-color", fillExpr());
    if (selected) showDetail(selected);
  };

  async function showDetail(id: string) {
    const f = gj.features.find((x: any) => x.properties.id === id);
    const series = levels.data[id];
    if (!f || !series) return;
    loadStations(id); // warm the cache so "Open detailed view" shows the wells at once
    $("detail").hidden = true; $("hint").hidden = true; $("detail").hidden = false;
    $("d-name").textContent = f.properties.name;
    const v = valueAt(id);
    const n = series.stations?.[seasonEl.value as Season]?.[Number(yearEl.value)];
    const mixed = series.mixed?.[seasonEl.value as Season]?.[Number(yearEl.value)];
    // The state, then the reading as a figure with what it is: season, year and how many wells
    const sub = $("d-sub");
    sub.className = "reading";
    sub.innerHTML = '<span class="state"></span><span class="figure"></span><span class="what"></span>';
    const [stateEl, figEl, whatEl] = Array.from(sub.children) as HTMLElement[];
    stateEl.textContent = f.properties.state;
    figEl.textContent = v == null ? "No data" : `${v.toFixed(1)} m`;
    whatEl.textContent = `${v == null ? "" : "below ground, "}${seasonEl.selectedOptions[0].text.toLowerCase()} ${levels.years[Number(yearEl.value)]}${v == null ? "" : stationsText(n)}`;
    if (v != null && mixed) sub.insertAdjacentHTML("beforeend", '<span class="estimated">Estimated: no manual wells this year.</span>');
    const { Chart, lineOptions, lineSet, stationsTooltip } = await loadCharts();
    if (selected !== id) return; // another district was picked while Chart.js loaded
    chart?.destroy();
    chart = new Chart($<HTMLCanvasElement>("chart"), {
      type: "line",
      data: { labels: levels.years, datasets: SEASONS.map((s) => lineSet(s, series[s], false)) },
      options: lineOptions(stationsTooltip(series.stations, SEASONS)),
    });
  }

  map.on("load", () => {
    fitIndia();
    map.addSource("d", { type: "geojson", data: gj });
    map.addLayer({ id: "fill", type: "fill", source: "d", paint: { "fill-color": noData(), "fill-opacity": 1 } });
    map.addLayer({ id: "line", type: "line", source: "d", paint: { "line-color": token("--map-line"), "line-width": 0.4 } });
    map.addLayer({ id: "sel", type: "line", source: "d", paint: { "line-color": token("--color-ink"), "line-width": 2.5 }, filter: ["==", ["get", "id"], selected ?? ""] });
    paint();
    map.on("click", "fill", (e) => {
      selected = e.features![0].properties!.id as string;
      map.setFilter("sel", ["==", ["get", "id"], selected]);
      showDetail(selected);
    });
    // Hover (mouse only): the district's name, state and value for the season and year on show
    const hover = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10, className: "district-pop" });
    map.on("mousemove", "fill", (e) => {
      map.getCanvas().style.cursor = "pointer";
      const p = e.features![0].properties!;
      if (p.id !== hoverId) {
        hoverId = p.id;
        const v = valueAt(p.id);
        const el = document.createElement("div");
        el.innerHTML = "<strong></strong><span class=\"pop-sub\"></span><span></span>";
        el.children[0].textContent = p.name;
        el.children[1].textContent = p.state;
        el.children[2].textContent = v == null ? "No data" : `${v.toFixed(1)} m below ground`;
        hover.setDOMContent(el);
      }
      hover.setLngLat(e.lngLat).addTo(map);
    });
    map.on("mouseleave", "fill", () => { map.getCanvas().style.cursor = ""; hover.remove(); hoverId = null; });
    // Once the map is up, fetch the chart and district-view code in the background so the first click is instant.
    const idle = (window as any).requestIdleCallback ?? ((f: () => void) => setTimeout(f, 1500));
    idle(() => { loadCharts(); import("./detail"); });
  });

  yearEl.addEventListener("input", () => map.isStyleLoaded() && paint());
  seasonEl.addEventListener("change", () => map.isStyleLoaded() && paint());

  let timer: number | undefined;
  $("play").addEventListener("click", (e) => {
    const btn = e.target as HTMLButtonElement;
    if (timer) { clearInterval(timer); timer = undefined; btn.textContent = "Play"; return; }
    btn.textContent = "Pause";
    if (yearEl.value === yearEl.max) yearEl.value = "0";
    timer = window.setInterval(() => {
      if (yearEl.value === yearEl.max) { clearInterval(timer); timer = undefined; btn.textContent = "Play"; return; }
      yearEl.value = String(Number(yearEl.value) + 1);
      paint();
    }, 600);
  });

  $("csv").addEventListener("click", () => {
    if (!selected) return;
    const s = levels.data[selected];
    const rows = ["year,pre_monsoon_m_bgl,post_monsoon_m_bgl,pre_monsoon_stations,post_monsoon_stations",
      ...levels.years.map((y, i) => `${y},${s.pre[i] ?? ""},${s.post[i] ?? ""},${s.stations?.pre[i] ?? ""},${s.stations?.post[i] ?? ""}`)];
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([rows.join("\n")], { type: "text/csv" }));
    a.download = `${selected}.csv`;
    a.click();
  });

  createSearch(gj, (id) => {
    const f = gj.features.find((x: any) => x.properties.id === id);
    selected = id;
    if (map.isStyleLoaded()) map.setFilter("sel", ["==", ["get", "id"], id]);
    moved = true; // the reader chose this view; keep it on resize
    map.fitBounds(bbox(f.geometry), { padding: 40, maxZoom: 8 });
    showDetail(id);
  });

  // Full-page district view, addressable as #district=<id> so it can be shared.
  let detailP: Promise<{ open(id: string, s: Season, yi: number): void; close(): void }> | null = null;
  const detail = () => (detailP ??= import("./detail").then((m) => m.createDetailView(gj, levels, (s, yi) => {
    seasonEl.value = s; yearEl.value = String(yi); // keep what the reader chose there
    requestAnimationFrame(fitIndia); // the map screen is visible again
    if (map.isStyleLoaded()) paint();
  })));
  $("open-detail").addEventListener("click", () => { if (selected) location.hash = `district=${selected}`; });
  const route = () => {
    const id = location.hash.match(/district=([\w-]+)/)?.[1];
    if (id && levels.data[id]) {
      selected = id;
      if (map.isStyleLoaded()) map.setFilter("sel", ["==", ["get", "id"], id]);
      detail().then((d) => d.open(id, seasonEl.value as Season, Number(yearEl.value)));
    } else detailP?.then((d) => d.close());
  };
  window.addEventListener("hashchange", route);
  route();
}

main();

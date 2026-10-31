import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { Chart } from "chart.js/auto";
import { $, base, bbox, CLASSES, colorFor, NO_DATA, stationsText, type Levels, type Season } from "./shared";
import { createDetailView } from "./detail";
import { createSearch } from "./search";

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
  let chart: Chart | null = null;

  const legend = $("legend");
  let lo = 0;
  for (const [max, c] of CLASSES) {
    legend.insertAdjacentHTML("beforeend", `<div><i style="background:${c}"></i>${max === Infinity ? `> ${lo}` : `${lo} – ${max}`} m</div>`);
    lo = max;
  }
  legend.insertAdjacentHTML("beforeend", `<div><i style="background:${NO_DATA}"></i>No data</div>`);

  const valueAt = (id: string) => levels.data[id]?.[seasonEl.value as Season]?.[Number(yearEl.value)] ?? null;

  const map = new maplibregl.Map({
    container: "map",
    style: { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": "#eef2f5" } }] },
    bounds: [[67, 6], [98, 38]],
    fitBoundsOptions: { padding: 20 },
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }));

  const paint = () => {
    $("year-out").textContent = String(levels.years[Number(yearEl.value)]);
    const expr: unknown[] = ["match", ["get", "id"]];
    for (const f of gj.features) expr.push(f.properties.id, colorFor(valueAt(f.properties.id)));
    expr.push(NO_DATA);
    map.setPaintProperty("fill", "fill-color", expr as maplibregl.ExpressionSpecification);
    if (selected) showDetail(selected);
  };

  function showDetail(id: string) {
    const f = gj.features.find((x: any) => x.properties.id === id);
    const series = levels.data[id];
    if (!f || !series) return;
    $("detail").hidden = true; $("hint").hidden = true; $("detail").hidden = false;
    $("d-name").textContent = f.properties.name;
    const v = valueAt(id);
    const n = series.stations?.[seasonEl.value as Season]?.[Number(yearEl.value)];
    const mixed = series.mixed?.[seasonEl.value as Season]?.[Number(yearEl.value)] ? "; estimated, no manual wells" : "";
    $("d-sub").textContent = `${f.properties.state} · ${levels.years[Number(yearEl.value)]} ${seasonEl.selectedOptions[0].text}: ${v == null ? "no data" : v.toFixed(1) + " m bgl" + stationsText(n).replace(/\)$/, mixed + ")")}`;
    chart?.destroy();
    chart = new Chart($<HTMLCanvasElement>("chart"), {
      type: "line",
      data: {
        labels: levels.years,
        datasets: (["pre", "post"] as Season[]).map((s) => ({
          label: s === "pre" ? "Pre-monsoon" : "Post-monsoon", data: series[s], spanGaps: false, pointRadius: 2,
          borderColor: s === "pre" ? "#d2793a" : "#1f5fa8", tension: 0.2,
        })),
      },
      options: {
        scales: { y: { reverse: true, title: { display: true, text: "m below ground" } } },
        plugins: {
          legend: { position: "bottom" },
          tooltip: { callbacks: { afterLabel: (c) => stationsText(series.stations?.[(["pre", "post"] as Season[])[c.datasetIndex]]?.[c.dataIndex]).trim() } },
        },
      },
    });
  }

  map.on("load", () => {
    map.addSource("d", { type: "geojson", data: gj });
    map.addLayer({ id: "fill", type: "fill", source: "d", paint: { "fill-color": NO_DATA, "fill-opacity": 0.9 } });
    map.addLayer({ id: "line", type: "line", source: "d", paint: { "line-color": "#ffffff", "line-width": 0.5 } });
    map.addLayer({ id: "sel", type: "line", source: "d", paint: { "line-color": "#000", "line-width": 2 }, filter: ["==", ["get", "id"], selected ?? ""] });
    paint();
    map.on("click", "fill", (e) => {
      selected = e.features![0].properties!.id as string;
      map.setFilter("sel", ["==", ["get", "id"], selected]);
      showDetail(selected);
    });
    map.on("mouseenter", "fill", () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", "fill", () => (map.getCanvas().style.cursor = ""));
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
    map.fitBounds(bbox(f.geometry), { padding: 40, maxZoom: 8 });
    showDetail(id);
  });

  // Full-page district view, addressable as #district=<id> so it can be shared.
  const detail = createDetailView(gj, levels, (s, yi) => {
    seasonEl.value = s; yearEl.value = String(yi); // keep what the reader chose there
    if (map.isStyleLoaded()) paint();
  });
  $("open-detail").addEventListener("click", () => { if (selected) location.hash = `district=${selected}`; });
  const route = () => {
    const id = location.hash.match(/district=([\w-]+)/)?.[1];
    if (id && levels.data[id]) {
      selected = id;
      if (map.isStyleLoaded()) map.setFilter("sel", ["==", ["get", "id"], id]);
      detail.open(id, seasonEl.value as Season, Number(yearEl.value));
    } else detail.close();
  };
  window.addEventListener("hashchange", route);
  route();
}

main();

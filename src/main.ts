import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { Chart } from "chart.js/auto";

type Season = "pre" | "post";
interface Levels {
  meta: { placeholder: boolean; source: string; unit: string };
  years: number[];
  // stations: how many stations each median is based on (absent in placeholder data)
  data: Record<string, Record<Season, (number | null)[]> & { stations?: Record<Season, number[]> }>;
}

const stationsText = (n: number | undefined) => n == null ? "" : ` (${n} station${n === 1 ? "" : "s"})`;

// Depth to water (m bgl) classes, sequential light -> dark; deeper is worse.
const CLASSES: [number, string][] = [
  [2, "#e6f2f7"], [5, "#b3d7e6"], [10, "#7fb7d4"], [20, "#e8c26a"], [40, "#d2793a"], [Infinity, "#8c2d1b"],
];
const NO_DATA = "#c9cdd2";
const colorFor = (v: number | null | undefined) => v == null ? NO_DATA : CLASSES.find(([max]) => v < max)![1];

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const base = import.meta.env.BASE_URL;

async function main() {
  const [gj, levels] = await Promise.all([
    fetch(`${base}data/districts.geojson`).then((r) => r.json()),
    fetch(`${base}data/levels.json`).then((r) => r.json() as Promise<Levels>),
  ]);
  $("banner").hidden = !levels.meta.placeholder;

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
    $("d-sub").textContent = `${f.properties.state} · ${levels.years[Number(yearEl.value)]} ${seasonEl.selectedOptions[0].text}: ${v == null ? "no data" : v.toFixed(1) + " m bgl" + stationsText(n)}`;
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
    map.addLayer({ id: "sel", type: "line", source: "d", paint: { "line-color": "#000", "line-width": 2 }, filter: ["==", ["get", "id"], ""] });
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
}

main();

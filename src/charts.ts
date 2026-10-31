// Chart.js and the shared line-chart setup. Imported lazily (first district pick), so the map
// screen's first load does not wait for it.
import { CategoryScale, Chart, Legend, LinearScale, LineController, LineElement, PointElement, Tooltip } from "chart.js";
import { SEASON_LABEL, stationsText, token, type Season } from "./shared";

// Only the pieces of Chart.js the line charts use (chart.js/auto pulls in every chart type).
Chart.register(LineController, LineElement, PointElement, LinearScale, CategoryScale, Tooltip, Legend);
export { Chart };

/** Point radius for a line series: a reading with no neighbour on either side is drawn as a dot,
 * since a line alone would not show it; every other point stays unmarked. */
export const loneDot = (r = 3) => (ctx: any) => {
  const d = ctx.dataset.data as (number | null)[], i = ctx.dataIndex;
  return d[i] != null && d[i - 1] == null && d[i + 1] == null ? r : 0;
};

/** Chart.js styling from the theme: pre-monsoon takes the accent, post-monsoon the warm second series colour. */
export const seriesColor = (s: Season) => token(s === "pre" ? "--color-series-pre" : "--color-series-post");
function chartTheme() {
  Chart.defaults.color = token("--color-muted");
  Chart.defaults.borderColor = token("--color-rule");
  Chart.defaults.font.family = getComputedStyle(document.documentElement).getPropertyValue("--font-body").trim();
  Chart.defaults.font.size = 12;
  Chart.defaults.plugins.legend.labels.color = token("--color-ink-2");
  Chart.defaults.plugins.legend.labels.boxWidth = 16;
  Chart.defaults.plugins.legend.labels.boxHeight = 2;
  Chart.defaults.plugins.tooltip.backgroundColor = token("--color-paper-3");
  Chart.defaults.plugins.tooltip.titleColor = token("--color-ink");
  Chart.defaults.plugins.tooltip.bodyColor = token("--color-ink");
  Chart.defaults.plugins.tooltip.borderColor = token("--color-rule");
  Chart.defaults.plugins.tooltip.borderWidth = 1;
  Chart.defaults.plugins.tooltip.cornerRadius = 0;
}

chartTheme();

/** One season's line: gaps left open for district series, bridged for a single well's sparse record. */
export const lineSet = (s: Season, data: (number | null)[], spanGaps: boolean) => ({
  label: SEASON_LABEL[s], data, spanGaps, pointRadius: spanGaps ? 0 : loneDot(), pointHoverRadius: 4,
  borderColor: seriesColor(s), backgroundColor: seriesColor(s), borderWidth: 2, tension: 0.2,
});
export const lineOptions = (extra: any = {}) => ({
  maintainAspectRatio: false,
  scales: { x: { grid: { display: false } }, y: { reverse: true, grace: "8%", title: { display: true, text: "m below ground" } } },
  plugins: { legend: { position: "bottom" as const }, ...extra },
});
/** Tooltip line with the number of stations behind each district value. */
export const stationsTooltip = (stations: Record<Season, number[]> | undefined, seasons: Season[]) =>
  ({ tooltip: { callbacks: { afterLabel: (c: any) => stationsText(stations?.[seasons[c.datasetIndex]]?.[c.dataIndex]).trim() } } });

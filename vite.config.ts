import { defineConfig, type Plugin } from "vite";

const SITE = "https://anchitm06.github.io/india-water-level-map/";
const REPO = "https://github.com/anchitm06/india-water-level-map";
const PAGES = [
  { file: "index.html", label: "Map" },
  { file: "guide.html", label: "How to use" },
  { file: "about.html", label: "About the data" },
];

/** Fills <!--SHARED-HEAD--> (icon, fonts, social cards from the page's own title and description) and
 * <!--SITE-NAV--> (links between the pages, the current one marked) in every page. */
function sharedChrome(): Plugin {
  const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
  return {
    name: "shared-chrome",
    transformIndexHtml(html, ctx) {
      const file = ctx.filename.split(/[\\/]/).pop()!;
      const title = html.match(/<title>([^<]*)<\/title>/)?.[1] ?? "India Groundwater Levels";
      const desc = html.match(/<meta name="description" content="([^"]*)"/)?.[1] ?? "";
      const url = SITE + (file === "index.html" ? "" : file);
      const head = `<meta name="theme-color" content="#fbfaf7" />
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Cpath d='M8 1C8 1 3 7 3 10a5 5 0 0 0 10 0C13 7 8 1 8 1z' fill='%23006186'/%3E%3C/svg%3E" />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Prata&family=Manrope:wght@400;500;700&display=swap" rel="stylesheet" />
  <meta property="og:type" content="website" />
  <meta property="og:site_name" content="India Groundwater Levels" />
  <meta property="og:title" content="${title}" />
  <meta property="og:description" content="${desc}" />
  <meta property="og:image" content="${SITE}og.png" />
  <meta property="og:image:width" content="1200" />
  <meta property="og:image:height" content="630" />
  <meta property="og:image:alt" content="Map of India's districts coloured by depth to groundwater" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="${title}" />
  <meta name="twitter:description" content="${desc}" />
  <meta name="twitter:image" content="${SITE}og.png" />
  <meta property="og:url" content="${url}" />
  <link rel="canonical" href="${url}" />`;
      const nav = `<nav class="site-nav" aria-label="Site">${PAGES.map((p) =>
        `<a href="./${p.file === "index.html" ? "" : p.file}"${p.file === file ? ' aria-current="page"' : ""}>${esc(p.label)}</a>`).join("")}<a href="${REPO}" rel="noopener">GitHub</a></nav>`;
      return html.replace("<!--SHARED-HEAD-->", head).replace(/<!--SITE-NAV-->/g, nav);
    },
  };
}

// base "./" keeps asset paths relative so the build works under any GitHub Pages sub-path.
export default defineConfig({
  base: "./",
  plugins: [sharedChrome()],
  build: {
    rollupOptions: {
      input: Object.fromEntries(PAGES.map((p) => [p.file.replace(".html", ""), p.file])),
      // MapLibre in its own long-lived file: app changes then don't make returning visitors re-download it
      output: { manualChunks: { maplibre: ["maplibre-gl"] } },
    },
    chunkSizeWarningLimit: 900, // MapLibre alone is ~800 kB minified (~210 kB gzipped); nothing to split further
  },
});

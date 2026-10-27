import { defineConfig } from "vite";

// base "./" keeps asset paths relative so the build works under any GitHub Pages sub-path.
export default defineConfig({ base: "./" });

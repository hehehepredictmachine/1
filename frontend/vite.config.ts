import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built files are served by the Python backend from the same origin (http://127.0.0.1:8765).
// Static files from public/ are served under /static/ by the backend.
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  base: "/",
  publicDir: "public",
  build: { outDir: mode === "test" ? "dist-test" : "dist", assetsDir: "assets", sourcemap: false, chunkSizeWarningLimit: 900,
           rollupOptions: { input: { main: "index.html", studio: "studio.html",                     // 1.33: separate Pepe Data & Training Studio entry
                                     ...(mode === "test" ? { chartsTest: "charts-test.html" } : {}) } } },   // test 1:1 CHARTS – tylko --mode test
}));

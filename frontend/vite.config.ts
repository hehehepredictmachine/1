import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 1.44.0 edycja: PMW_EDITION=CLIENT buduje panel klienta – kod generatora licencji (wersja właściciela) jest wycinany przy kompilacji
// (__PMW_EDITION__ === "OWNER" -> false), więc w paczce klienta nie ma go wcale (tools/build_release.py --edition client).
const EDITION = process.env.PMW_EDITION === "CLIENT" ? "CLIENT" : "OWNER";

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  define: { __PMW_EDITION__: JSON.stringify(EDITION) },
  base: "/",
  publicDir: "public",
  build: { outDir: mode === "test" ? "dist-test" : "dist", assetsDir: "assets", sourcemap: false, chunkSizeWarningLimit: 1000,
           rollupOptions: { input: { main: "index.html", studio: "studio.html",                     // 1.33: separate Pepe Data & Training Studio entry
                                     ...(mode === "test" ? { chartsTest: "charts-test.html" } : {}) } } },   // testy 1:1 – tylko --mode test
}));

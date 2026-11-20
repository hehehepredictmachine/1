import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";

// Intro 3D: bryła postaci (assets/body.bin.gz) dołączana bajt w bajt jako Uint8Array – jak loader `binary` esbuild we wzorcu (build.sh);
// trafia tylko do leniwego fragmentu intro (CSP 'self', bez fetch z innego źródła).
const binaryGz = { name: "pmw-binary-gz", enforce: "pre" as const,
  load(id: string) { if (!id.endsWith(".bin.gz")) return null;
    return `const b=${JSON.stringify(readFileSync(id).toString("base64"))};const s=atob(b),u=new Uint8Array(s.length);for(let i=0;i<s.length;i++)u[i]=s.charCodeAt(i);export default u;`; } };

// Built files are served by the Python backend from the same origin (http://127.0.0.1:8765).
// Static files from public/ are served under /static/ by the backend.
// 1.44.0 edycja: PMW_EDITION=CLIENT buduje panel klienta – kod generatora licencji (wersja właściciela) jest wycinany przy kompilacji
// (__PMW_EDITION__ === "OWNER" -> false), więc w paczce klienta nie ma go wcale (tools/build_release.py --edition client).
const EDITION = process.env.PMW_EDITION === "CLIENT" ? "CLIENT" : "OWNER";

export default defineConfig(({ mode }) => ({
  plugins: [binaryGz, react()],
  define: { __PMW_EDITION__: JSON.stringify(EDITION) },
  base: "/",
  publicDir: "public",
  build: { outDir: mode === "test" ? "dist-test" : "dist", assetsDir: "assets", sourcemap: false, chunkSizeWarningLimit: 2600,   // intro3d (three.js + bryła postaci) – leniwy fragment ~2,5 MB
           rollupOptions: { input: { main: "index.html", studio: "studio.html",                     // 1.33: separate Pepe Data & Training Studio entry
                                     ...(mode === "test" ? { chartsTest: "charts-test.html", introTest: "intro-test.html" } : {}) } } },   // testy 1:1 – tylko --mode test
}));

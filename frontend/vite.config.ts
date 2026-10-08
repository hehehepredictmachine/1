import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built files are served by the Python backend from the same origin (http://127.0.0.1:8765).
// Static files from public/ are served under /static/ by the backend.
export default defineConfig({
  plugins: [react()],
  base: "/",
  publicDir: "public",
  build: { outDir: "dist", assetsDir: "assets", sourcemap: false, chunkSizeWarningLimit: 900 },
});

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

// Two entry points served by the central server: /admin/ (MasterQUO License Manager) and /account/ (public account pages).
export default defineConfig({
  plugins: [react()],
  base: "/",
  build: {
    outDir: "dist", assetsDir: "assets", sourcemap: false,
    rollupOptions: { input: { admin: resolve(__dirname, "admin.html"), account: resolve(__dirname, "account.html") } },
  },
});

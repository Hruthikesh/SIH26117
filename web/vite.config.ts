import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

// Static build served by the server from server/yantra_server/static.
// No CDN: everything is inlined/bundled so the dashboard makes zero external requests.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: resolve(__dirname, "../server/yantra_server/static"),
    emptyOutDir: true,
    assetsInlineLimit: 100_000_000, // inline all assets → single self-contained bundle
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:7331",
      "/rpc": { target: "ws://127.0.0.1:7331", ws: true },
    },
  },
});

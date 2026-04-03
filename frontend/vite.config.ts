import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5180,
    // Allow ngrok domains for remote preview.
    allowedHosts: [".ngrok-free.dev"],
    proxy: {
      "/api": { target: "http://127.0.0.1:8010", changeOrigin: true },
    },
  },
  build: {
    outDir: "../server/static",
    emptyOutDir: true,
  },
});

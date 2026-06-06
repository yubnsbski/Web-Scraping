import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// During development the Python API runs on :8000; proxy /api to it so the
// frontend can call relative paths in both dev and production (served by the
// Python server from web/dist).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
  },
});

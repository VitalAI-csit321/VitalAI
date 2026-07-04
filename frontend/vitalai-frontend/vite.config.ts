import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      // Forward all /api/v1/* calls to the FastAPI backend in dev
      // Backend already uses /api/v1/ prefix — no path rewriting needed
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});

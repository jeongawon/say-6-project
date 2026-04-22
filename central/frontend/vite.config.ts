import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/triage": "http://localhost:8000",
      "/orders": "http://localhost:8000",
      "/encounters": "http://localhost:8000",
      "/reports": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
});

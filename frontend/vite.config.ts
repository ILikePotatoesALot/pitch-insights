import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the replay server runs on :8000; Vite forwards API and WebSocket calls to it.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
});

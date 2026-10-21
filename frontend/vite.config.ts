import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the replay server runs on :8000 (or wherever PITCH_API points, e.g. 127.0.0.1:8001);
// Vite forwards API and WebSocket calls to it.
const api = process.env.PITCH_API ?? "127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": `http://${api}`,
      "/ws": { target: `ws://${api}`, ws: true },
    },
  },
});

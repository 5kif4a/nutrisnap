import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In dev we proxy /api → FastAPI so the browser never hits CORS and the
// app can use a relative API base. In prod, VITE_API_URL points at Railway.
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    // Allow ngrok tunnels so the Telegram Mini App can load the dev server
    // over https. `.ngrok-free.app` matches any subdomain on the free tier.
    allowedHosts: [".ngrok-free.app", ".ngrok.io"],
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});

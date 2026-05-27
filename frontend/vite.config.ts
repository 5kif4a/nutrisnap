import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In dev we proxy /api → FastAPI so the browser never hits CORS and the
// app can use a relative API base. In prod, VITE_API_URL points at Railway.
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        // Split heavy third-party deps into long-lived cacheable chunks.
        // Editing app code won't invalidate vendor chunks, so repeat visits
        // re-download only the small app bundle.
        manualChunks(id) {
          if (!id.includes("node_modules")) return;
          // `scheduler` is a React internal — keep it next to react/-dom so we
          // don't get a circular reference between vendor and vendor-react.
          if (
            id.includes("react-dom") ||
            id.includes("scheduler") ||
            id.match(/[\\/]react[\\/]/)
          ) {
            return "vendor-react";
          }
          if (id.includes("@telegram-apps")) return "vendor-telegram";
          if (
            id.includes("react-hook-form") ||
            id.includes("@hookform/resolvers") ||
            id.includes("/zod/")
          ) {
            return "vendor-form";
          }
          if (id.includes("lucide-react")) return "vendor-icons";
          // Anything else from node_modules stays in the default chunk —
          // returning undefined avoids forcing a separate "vendor" chunk
          // that would create a circular dep with vendor-react.
          return undefined;
        },
      },
    },
  },
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

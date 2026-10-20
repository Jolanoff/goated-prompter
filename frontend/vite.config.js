import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    // The API trusts only its own origin, so the proxy presents it (Host is already rewritten by changeOrigin).
    proxy: (() => {
      const target = `http://127.0.0.1:${process.env.GOATED_UI_TEST_PORT || "8190"}`;
      return { "/api": { target, changeOrigin: true, headers: { Origin: target } } };
    })(),
  },
});

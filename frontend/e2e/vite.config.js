import base from "../vite.config.js";

// The production API trusts its own origin and the standard Vite port only.
export default { ...base, server: { port: 5191, strictPort: true, proxy: { "/api": { target: "http://127.0.0.1:8191", changeOrigin: true, headers: { Origin: "http://127.0.0.1:8191" } } } } };

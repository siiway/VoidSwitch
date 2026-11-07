import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// Minimalist, fast-render setup. No source maps in prod for lean output.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd());
  const apiTarget = env.VITE_API_PROXY || "http://127.0.0.1:8080";
  return {
    plugins: [react()],
    server: {
      port: env.VITE_PORT ? Number(env.VITE_PORT) : 5173,
      proxy: {
        "/api": { target: apiTarget, changeOrigin: true },
        "/v1": { target: apiTarget, changeOrigin: true },
        "/provider-api": { target: apiTarget, changeOrigin: true },
        "/healthz": { target: apiTarget, changeOrigin: true },
        "/install": { target: apiTarget, changeOrigin: true },
        "/opencode": { target: apiTarget, changeOrigin: true },
      },
    },
    preview: {
      port: 4173,
    },
    build: {
      target: "es2022",
      sourcemap: false,
    },
  };
});

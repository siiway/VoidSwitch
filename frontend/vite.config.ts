import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// Minimalist, fast-render setup. No source maps in prod for lean output.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd());
  return {
    plugins: [react()],
    server: {
      port: env.VITE_PORT ? Number(env.VITE_PORT) : 5173,
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

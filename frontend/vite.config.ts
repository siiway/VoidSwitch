import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Minimalist, fast-render setup. No source maps in prod for lean output.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
  preview: {
    port: 4173,
  },
  build: {
    target: "es2022",
    sourcemap: false,
  },
});

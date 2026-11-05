import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Relative asset URLs: the same build is served at / and under /fin (see fin/api.py).
export default defineConfig({
  base: "./",
  plugins: [react(), tailwindcss()],
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8742" } },
  build: { outDir: "dist", emptyOutDir: true },
});

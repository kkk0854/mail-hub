import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            { name: "vendor", test: /node_modules\/(react|react-dom|react-router-dom|zustand|@tanstack|clsx)/ },
            { name: "charts", test: /node_modules\/recharts/ },
          ],
        },
      },
    },
  },
});

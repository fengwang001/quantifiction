import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 仅监听本地/Tailscale，不暴露公网（宪法 IV / R8）
export default defineConfig({
  plugins: [react()],
  server: { host: "127.0.0.1", port: 5173 },
});

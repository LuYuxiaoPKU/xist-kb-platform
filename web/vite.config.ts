import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The API and the static build are served by one uvicorn process in
// production; during development Vite proxies /api there so the frontend can
// be edited with hot reload while the real data layer answers.
//
// 8420 rather than the more customary 8000: this machine already runs another
// service there, and the two cannot share a port. The server keeps the same
// number so the dev proxy and production agree.
const API_PORT = process.env.XIST_KB_PORT ?? '8420'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${API_PORT}`,
        changeOrigin: true,
      },
    },
  },
  build: { outDir: 'dist', sourcemap: false },
})

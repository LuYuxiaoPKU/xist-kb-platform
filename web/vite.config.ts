import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The API and the static build are served by one uvicorn process in
// production; during development Vite proxies /api there so the frontend can
// be edited with hot reload while the real data layer answers.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: { outDir: 'dist', sourcemap: false },
})

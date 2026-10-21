import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Backend dev server. Override with MOCADIFF_BACKEND when testing against a
// scratch port; the app itself always talks to relative /api + /media URLs so
// the production build served by FastAPI works without any changes.
const BACKEND = process.env.MOCADIFF_BACKEND ?? 'http://127.0.0.1:8787'

const proxy = {
  '/api': { target: BACKEND, changeOrigin: false },
  '/media': { target: BACKEND, changeOrigin: false },
}

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy,
  },
  preview: {
    host: '127.0.0.1',
    port: 4173,
    strictPort: true,
    proxy,
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 1200,
  },
})

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // The dev server proxies to the local backend so the browser sees one origin and CORS
    // never enters the picture while developing. In production the frontend is static files
    // on Cloudflare Pages and VITE_API_BASE_URL points at Cloud Run.
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/health': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: {
    // Source maps make a production bug reportable. They cost bandwidth on first load only
    // and are not fetched unless devtools is open.
    sourcemap: true,
  },
})

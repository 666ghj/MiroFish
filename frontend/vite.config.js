import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
      '@locales': path.resolve(__dirname, '../locales')
    }
  },
  server: {
    host: true,          // bind 0.0.0.0 so the box is reachable on the LAN
    port: 3000,
    strictPort: true,    // fail loudly instead of silently sliding to 3001,
                         // which would leave firewall rules pointing at nothing
    open: false,         // headless server: `open` shells out to xdg-open and fails
    // Set VITE_ALLOWED_HOSTS to a comma-separated list to reach the UI by
    // hostname; Vite blocks unknown Host headers (bare IPs are always allowed).
    allowedHosts: process.env.VITE_ALLOWED_HOSTS
      ? process.env.VITE_ALLOWED_HOSTS.split(',').map((h) => h.trim())
      : undefined,
    proxy: {
      // The frontend now uses same-origin relative URLs (src/api/index.js), so
      // this proxy is the only path from browser to backend. That is what lets
      // a single exposed port serve the whole app.
      '/api': {
        target: process.env.VITE_PROXY_TARGET || 'http://127.0.0.1:5001',
        changeOrigin: true,
        secure: false
      }
    }
  }
})

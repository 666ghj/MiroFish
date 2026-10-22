import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      // frontend-local copy of the shared locales (Vercel builds only include
      // files inside frontend/, so the repo-root locales/ used by the backend
      // is not available at build time — keep both in sync when adding keys)
      '@': path.resolve(__dirname, 'src'),
      '@locales': path.resolve(__dirname, './locales')
    }
  },
  server: {
    port: 3000,
    open: true,
    proxy: {
      '/api': {
        target: 'http://localhost:5001',
        changeOrigin: true,
        secure: false
      }
    }
  }
})

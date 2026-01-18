import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const apiBaseUrl = process.env.VITE_API_BASE_URL || 'http://localhost:5001'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 3000,
    open: true,
    proxy: {
      '/api': {
        target: apiBaseUrl,
        changeOrigin: true,
        secure: false
      }
    }
  }
})

import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, path.resolve(__dirname, '..'), '')
  return {
    envDir: path.resolve(__dirname, '..'),
    plugins: [vue()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, 'src'),
        '@locales': path.resolve(__dirname, '../locales')
      }
    },
    server: {
      port: Number(env.FRONTEND_PORT || 4317),
      strictPort: true,
      open: true,
      proxy: {
        '/api': {
          target: `http://127.0.0.1:${env.FLASK_PORT || 5001}`,
          changeOrigin: true,
          secure: false
        }
      }
    }
  }
})

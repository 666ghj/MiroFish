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
    port: 3000,
    open: true,
    proxy: {
      '/api': {
        target: 'http://localhost:5001',
        changeOrigin: true,
        secure: false
      }
    }
  },
  // C1：生产镜像用 `vite preview` 提供已构建的静态产物（而非开发服务器）。
  // preview 默认不套用 server.proxy，需单独声明，否则 /api 不被转发到后端。
  // host:'0.0.0.0' 必需：默认仅绑 localhost，在容器内会让 Docker 端口映射（3000:3000）无法触达。
  preview: {
    host: '0.0.0.0',
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:5001',
        changeOrigin: true,
        secure: false
      }
    }
  }
})

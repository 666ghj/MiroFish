import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

function parseAllowedHosts(value) {
  if (!value) {
    return ['localhost', '127.0.0.1', '.ts.net', '.beta.tailscale.net']
  }

  return value
    .split(',')
    .map(item => item.trim())
    .filter(Boolean)
}

function buildHmrConfig(env) {
  const hmr = {}

  if (env.VITE_HMR_HOST) hmr.host = env.VITE_HMR_HOST
  if (env.VITE_HMR_PROTOCOL) hmr.protocol = env.VITE_HMR_PROTOCOL
  if (env.VITE_HMR_PORT) hmr.port = Number(env.VITE_HMR_PORT)
  if (env.VITE_HMR_CLIENT_PORT) hmr.clientPort = Number(env.VITE_HMR_CLIENT_PORT)
  if (env.VITE_HMR_PATH) hmr.path = env.VITE_HMR_PATH

  return Object.keys(hmr).length ? hmr : undefined
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const repoRoot = path.resolve(__dirname, '..')
  const rootEnv = loadEnv(mode, repoRoot, '')
  const frontendEnv = loadEnv(mode, __dirname, '')
  const env = { ...rootEnv, ...frontendEnv, ...process.env }

  return {
    plugins: [vue()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, 'src'),
        '@locales': path.resolve(__dirname, '../locales')
      }
    },
    server: {
      host: env.VITE_DEV_HOST || '0.0.0.0',
      port: Number(env.VITE_DEV_PORT || 3000),
      strictPort: true,
      open: env.VITE_OPEN_BROWSER ? env.VITE_OPEN_BROWSER === 'true' : true,
      allowedHosts: parseAllowedHosts(env.VITE_ALLOWED_HOSTS),
      hmr: buildHmrConfig(env),
      proxy: {
        '/api': {
          target: env.VITE_DEV_PROXY_TARGET || 'http://127.0.0.1:5001',
          changeOrigin: true,
          secure: false
        }
      }
    }
  }
})

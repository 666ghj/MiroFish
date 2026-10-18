import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

const repoRoot = path.resolve(__dirname, '..')

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  if (mode === 'production' && process.env.VITE_REQUIRE_WAITLIST_CONFIG === 'true') {
    const env = loadEnv(mode, repoRoot, '')
    const missing = ['VITE_SUPABASE_URL', 'VITE_SUPABASE_ANON_KEY'].filter(
      (key) => !env[key]?.trim()
    )
    if (missing.length) {
      throw new Error(`Missing waitlist env for marketing deploy: ${missing.join(', ')}`)
    }
  }

  return {
    envDir: repoRoot,
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
    }
  }
})

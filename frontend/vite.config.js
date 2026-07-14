import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // Load .env files so VITE_API_PROXY_TARGET is honoured here. Vite only exposes
  // .env values to client code via import.meta.env; the dev-server config must
  // read them explicitly with loadEnv, otherwise process.env is empty for them.
  const env = loadEnv(mode, process.cwd(), '')
  const proxyTarget = env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8010'

  return {
    plugins: [vue()],
    // Avoid Vite's Windows realpath optimisation, which launches `net use` and
    // can fail with spawn EPERM on locked-down Windows environments.
    resolve: {
      preserveSymlinks: true,
    },
    server: {
      host: '0.0.0.0',
      allowedHosts: ['localhost', '127.0.0.1', '.trycloudflare.com'],
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true,
        },
      },
    },
  }
})

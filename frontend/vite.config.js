import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { hostname } from 'node:os'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // Load .env files so VITE_API_PROXY_TARGET is honoured here. Vite only exposes
  // .env values to client code via import.meta.env; the dev-server config must
  // read them explicitly with loadEnv, otherwise process.env is empty for them.
  const env = loadEnv(mode, process.cwd(), '')
  const proxyTarget = env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8010'
  const extraAllowedHosts = (env.VITE_ALLOWED_HOSTS || '')
    .split(',')
    .map(value => value.trim())
    .filter(Boolean)
  const machineHostname = hostname()
  const allowedHosts = [...new Set([
    'localhost',
    '127.0.0.1',
    machineHostname,
    machineHostname.toLowerCase(),
    ...extraAllowedHosts,
  ])]

  return {
    plugins: [vue()],
    // Avoid Vite's Windows realpath optimisation, which launches `net use` and
    // can fail with spawn EPERM on locked-down Windows environments.
    resolve: {
      preserveSymlinks: true,
    },
    server: {
      host: '0.0.0.0',
      port: 5173,
      strictPort: true,
      allowedHosts,
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true,
        },
      },
    },
    // Mirror the dev server so `vite preview` (built static assets served as the
    // LAN "production") keeps hostname access and /api proxying working.
    preview: {
      host: '0.0.0.0',
      port: 5173,
      strictPort: true,
      allowedHosts,
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true,
        },
      },
    },
  }
})

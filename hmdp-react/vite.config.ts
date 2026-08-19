import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const agentProxyTarget = process.env.VITE_AGENT_PROXY_TARGET || 'http://127.0.0.1:8090'
const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8081'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: apiProxyTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
      '/agent-api': {
        target: agentProxyTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/agent-api/, ''),
      },
    },
  },
  build: {
    outDir: 'dist',
  },
})

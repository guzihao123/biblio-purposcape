import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

const acceptanceApiOrigin = `http://127.0.0.1:${process.env.ACCEPTANCE_BACKEND_PORT || '8000'}`

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': acceptanceApiOrigin,
      '/functions/v1/app': {
        target: acceptanceApiOrigin,
        rewrite: (path) => path.replace(/^\/functions\/v1\/app/, '/api'),
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    exclude: ['**/node_modules/**', '**/dist/**', '**/e2e/**'],
    css: true,
    clearMocks: true,
  },
})

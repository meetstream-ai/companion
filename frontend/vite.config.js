import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Vitest transforms test files itself (not through the React plugin) and
  // still reads the esbuild key for the automatic JSX runtime; Vite 8's build
  // ignores that key with a warning, so it is only set for test runs.
  ...(process.env.VITEST ? { esbuild: { jsx: 'automatic' } } : {}),
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.js'],
  },
  server: {
    port: 3000,
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})

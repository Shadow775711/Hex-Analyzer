import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    // `npm run dev`: /api goes to the locally running backend (uvicorn :8000),
    // so the frontend and the API share one address — no CORS, just like in Docker.
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  build: {
    sourcemap: false,
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.js',
  },
});

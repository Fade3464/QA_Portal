import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': process.env.VITE_API_PROXY_TARGET ?? 'http://127.0.0.1:8000',
      '/django-admin': process.env.VITE_API_PROXY_TARGET ?? 'http://127.0.0.1:8000',
      '/static': process.env.VITE_API_PROXY_TARGET ?? 'http://127.0.0.1:8000',
      '/ws': { target: process.env.VITE_WS_PROXY_TARGET ?? 'ws://127.0.0.1:8000', ws: true },
    },
  },
});

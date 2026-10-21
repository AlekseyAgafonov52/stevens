import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  base: './',
  server: {
    port: 5174,
    strictPort: true,
    proxy: { '/api/tts': 'http://localhost:8001', '/api': 'http://localhost:8000' },
  },
});

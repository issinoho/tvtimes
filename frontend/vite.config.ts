import { fileURLToPath, URL } from 'node:url';

import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'prompt',
      injectRegister: false,
      includeAssets: ['favicon.svg', 'maskable-icon.svg'],
      manifest: {
        name: 'tvtimes',
        short_name: 'tvtimes',
        description: 'A modern, multi-tenant TV schedule guide.',
        theme_color: '#0B0713',
        background_color: '#0B0713',
        display: 'standalone',
        start_url: '/',
        icons: [
          // Two separate entries on purpose. favicon.svg is drawn as a TV with
          // a margin, which Android's maskable crop (central 80%, then a
          // circle/squircle mask) slices the sides off. maskable-icon.svg is
          // the full-bleed variant built for that crop.
          { src: 'favicon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any' },
          {
            src: 'maskable-icon.svg',
            sizes: 'any',
            type: 'image/svg+xml',
            purpose: 'maskable',
          },
        ],
      },
      workbox: {
        // Precache the built app shell for offline launch; never cache /api.
        navigateFallbackDenylist: [/^\/api/],
        runtimeCaching: [],
      },
    }),
  ],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/openapi.json': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: true,
    // *.browser.test.tsx run in a real browser via vitest.browser.config.ts.
    // They assert layout, so jsdom -- which has no box model -- would fail
    // them for the wrong reason.
    exclude: ['**/node_modules/**', '**/dist/**', '**/*.browser.test.{ts,tsx}'],
  },
});

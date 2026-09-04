import { fileURLToPath, URL } from 'node:url';

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

/**
 * Layout tests, in a real browser.
 *
 * The jsdom suite can't see layout at all — it has no box model, so two
 * elements overlapping, text with no contrast, and a button scrolled off the
 * viewport all look identical to a passing test. Four such bugs shipped past
 * a green suite; these are the assertions that would have caught them.
 *
 * Deliberately separate from the main config: `npm test` stays fast and needs
 * no browser, and this runs as its own step. Keep it to things that genuinely
 * need layout — behaviour belongs in the jsdom suite.
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  test: {
    include: ['src/**/*.browser.test.{ts,tsx}'],
    css: true,
    browser: {
      enabled: true,
      provider: 'playwright',
      headless: true,
      screenshotFailures: false,
      instances: [{ browser: 'chromium' }],
    },
  },
});

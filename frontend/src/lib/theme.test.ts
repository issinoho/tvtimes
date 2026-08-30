import { afterEach, beforeEach, expect, test } from 'vitest';

import { applyTheme, loadTheme, nextTheme } from '@/lib/theme';

beforeEach(() => localStorage.clear());
afterEach(() => document.documentElement.removeAttribute('data-theme'));

test('nextTheme cycles system -> light -> dark -> system', () => {
  expect(nextTheme('system')).toBe('light');
  expect(nextTheme('light')).toBe('dark');
  expect(nextTheme('dark')).toBe('system');
});

test('applyTheme stamps the root and persists, system clears it', () => {
  applyTheme('dark');
  expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
  expect(loadTheme()).toBe('dark');

  applyTheme('system');
  expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
  expect(loadTheme()).toBe('system');
});

test('loadTheme falls back to system for junk', () => {
  localStorage.setItem('tvtimes.theme', 'neon');
  expect(loadTheme()).toBe('system');
});

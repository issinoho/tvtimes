import { afterEach, expect, test, vi } from 'vitest';

import { isAndroid } from '@/lib/platform';

const UA = (value: string) => vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue(value);

afterEach(() => vi.restoreAllMocks());

test('isAndroid is true for an Android Chrome UA', () => {
  UA(
    'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Mobile Safari/537.36',
  );
  expect(isAndroid()).toBe(true);
});

test('isAndroid is false for desktop UAs', () => {
  UA('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36');
  expect(isAndroid()).toBe(false);
  UA('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36');
  expect(isAndroid()).toBe(false);
});

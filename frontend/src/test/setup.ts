import '@testing-library/jest-dom/vitest';
import { vi } from 'vitest';

// jsdom ships neither of these; a couple of components touch them.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver;

if (!window.HTMLElement.prototype.scrollTo) {
  window.HTMLElement.prototype.scrollTo = vi.fn();
}

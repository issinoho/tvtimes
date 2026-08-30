import { useEffect, useRef } from 'react';

/**
 * On mount: move focus into the dialog (the first focusable element, or the
 * container itself). On unmount: restore focus to whatever had it before.
 * Also keeps Tab within the dialog.
 */
export function useDialogFocus<T extends HTMLElement>() {
  const ref = useRef<T>(null);

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const node = ref.current;
    const focusables = () =>
      Array.from(
        node?.querySelectorAll<HTMLElement>(
          'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])',
        ) ?? [],
      );

    (focusables()[0] ?? node)?.focus();

    function onKeyDown(e: KeyboardEvent) {
      if (e.key !== 'Tab') return;
      const items = focusables();
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }

    node?.addEventListener('keydown', onKeyDown);
    return () => {
      node?.removeEventListener('keydown', onKeyDown);
      opener?.focus?.();
    };
  }, []);

  return ref;
}

import { useRegisterSW } from 'virtual:pwa-register/react';

import styles from './pwa.module.css';

const CHECK_EVERY_MS = 60 * 60 * 1000;

/**
 * When a new build is deployed the service worker fetches it in the background
 * and waits; this shows a toast so the user activates it with one click instead
 * of a hard reload / clearing site data.
 */
export function UpdatePrompt() {
  const {
    needRefresh: [needRefresh, setNeedRefresh],
    updateServiceWorker,
  } = useRegisterSW({
    onRegisteredSW(_swUrl, registration) {
      if (registration) {
        setInterval(() => void registration.update(), CHECK_EVERY_MS);
      }
    },
  });

  if (!needRefresh) return null;

  return (
    <div className={styles.toast} role="status" aria-live="polite">
      <span>A new version of tvtimes is available.</span>
      <button
        type="button"
        className={styles.reload}
        onClick={() => void updateServiceWorker(true)}
      >
        Reload
      </button>
      <button type="button" className={styles.later} onClick={() => setNeedRefresh(false)}>
        Later
      </button>
    </div>
  );
}

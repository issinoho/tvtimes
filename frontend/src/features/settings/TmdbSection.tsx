import { useState } from 'react';

import { api, ApiError, unwrap } from '@/lib/api/client';
import { useAuth } from '@/lib/auth/AuthProvider';
import styles from '@/features/settings/settings.module.css';

export function TmdbSection() {
  const { user, refreshMe } = useAuth();
  const connected = user?.tmdb_connected ?? false;
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState(false);

  async function connect() {
    setBusy(true);
    setError(null);
    setOk(false);
    try {
      unwrap(await api.PUT('/api/account/tmdb-token', { body: { token: token.trim() } }));
      setToken('');
      setOk(true);
      await refreshMe();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save that key.');
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    setBusy(true);
    setError(null);
    try {
      unwrap(await api.DELETE('/api/account/tmdb-token'));
      await refreshMe();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not disconnect.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={styles.section}>
      <h2>
        TMDB
        {connected ? <span className={styles.badge}>connected</span> : null}
      </h2>
      <p className={styles.hint}>
        Add a free{' '}
        <a
          href="https://www.themoviedb.org/settings/api"
          target="_blank"
          rel="noreferrer noopener"
          className="linkish"
        >
          TMDB API Read Access Token (v4)
        </a>{' '}
        and the guide enriches films and shows with backdrops, cast, ratings and synopses.
      </p>

      {connected ? (
        <div className={styles.actions}>
          <button
            type="button"
            className={`${styles.btn} ${styles.danger}`}
            onClick={disconnect}
            disabled={busy}
          >
            Disconnect
          </button>
        </div>
      ) : (
        <>
          <input
            className={styles.select}
            style={{ minWidth: 320, maxWidth: '100%' }}
            placeholder="eyJhbGciOi…"
            value={token}
            onChange={(e) => setToken(e.target.value)}
          />
          <div className={styles.actions}>
            <button
              type="button"
              className={`${styles.btn} ${styles.primary}`}
              onClick={connect}
              disabled={busy || token.trim().length < 20}
            >
              {busy ? 'Checking…' : 'Connect'}
            </button>
          </div>
        </>
      )}
      {ok ? <p className={styles.ok}>Connected. New guide data will fill in shortly.</p> : null}
      {error ? <p className={styles.error}>{error}</p> : null}
      <p className={styles.hint} style={{ marginTop: '0.75rem' }}>
        This product uses the TMDB API but is not endorsed or certified by TMDB.
      </p>
    </section>
  );
}

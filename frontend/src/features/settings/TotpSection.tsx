import { useState } from 'react';
import QRCode from 'qrcode';

import { api, ApiError, unwrap } from '@/lib/api/client';
import { useAuth } from '@/lib/auth/AuthProvider';
import styles from '@/features/settings/settings.module.css';

type Enrol = { secret: string; qr: string };

export function TotpSection() {
  const { user, refreshMe } = useAuth();
  const enabled = user?.totp_enabled ?? false;

  const [enrol, setEnrol] = useState<Enrol | null>(null);
  const [code, setCode] = useState('');
  const [recovery, setRecovery] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function begin() {
    setBusy(true);
    setError(null);
    try {
      const res = unwrap(await api.POST('/api/account/totp'));
      const qr = await QRCode.toDataURL(res.provisioning_uri, { margin: 1, width: 320 });
      setEnrol({ secret: res.secret, qr });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not start setup.');
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      const res = unwrap(
        await api.POST('/api/account/totp/confirm', { body: { code: code.trim() } }),
      );
      setRecovery(res.recovery_codes);
      setEnrol(null);
      setCode('');
      await refreshMe();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'That code was not accepted.');
    } finally {
      setBusy(false);
    }
  }

  async function disable() {
    if (!window.confirm('Turn off two-factor authentication?')) return;
    setBusy(true);
    setError(null);
    try {
      unwrap(await api.DELETE('/api/account/totp'));
      setRecovery(null);
      await refreshMe();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not disable.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={styles.section}>
      <h2>
        Two-factor authentication
        {enabled ? <span className={styles.badge}>on</span> : null}
      </h2>
      <p className={styles.hint}>
        A time-based code from an authenticator app, asked for after your password. Passkey sign-in
        already covers this, so this is mainly a backstop for password logins.
      </p>

      {recovery ? (
        <div>
          <p className={styles.ok}>
            Two-factor is on. Save these recovery codes somewhere safe — each works once if you lose
            your authenticator.
          </p>
          <ol className={styles.codes}>
            {recovery.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ol>
        </div>
      ) : null}

      {!enabled && !enrol ? (
        <div className={styles.actions}>
          <button
            type="button"
            className={`${styles.btn} ${styles.primary}`}
            onClick={begin}
            disabled={busy}
          >
            Set up
          </button>
        </div>
      ) : null}

      {enrol ? (
        <div>
          <div className={styles.totpSetup}>
            <img src={enrol.qr} alt="TOTP setup QR code" />
            <div>
              <p className={styles.hint}>Scan in your authenticator app, or enter this key:</p>
              <p className={styles.secret}>{enrol.secret}</p>
              <input
                className={styles.select}
                inputMode="numeric"
                autoComplete="one-time-code"
                placeholder="6-digit code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
              />
            </div>
          </div>
          <div className={styles.actions}>
            <button
              type="button"
              className={`${styles.btn} ${styles.primary}`}
              onClick={confirm}
              disabled={busy}
            >
              Confirm
            </button>
            <button type="button" className={styles.btn} onClick={() => setEnrol(null)}>
              Cancel
            </button>
          </div>
        </div>
      ) : null}

      {enabled ? (
        <div className={styles.actions}>
          <button
            type="button"
            className={`${styles.btn} ${styles.danger}`}
            onClick={disable}
            disabled={busy}
          >
            Turn off
          </button>
        </div>
      ) : null}

      {error ? <p className={styles.error}>{error}</p> : null}
    </section>
  );
}

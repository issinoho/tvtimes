import { Link } from 'react-router-dom';

import { useAuth } from '@/lib/auth/AuthProvider';
import styles from '@/features/app/AppLayout.module.css';

export function HomePage() {
  const { user } = useAuth();

  return (
    <div>
      {user && !user.email_verified ? (
        <p className={styles.verifyBanner}>
          Your email isn't verified yet. Check your inbox for the confirmation link — some features
          stay locked until you do.
        </p>
      ) : null}

      <div className={styles.hero}>
        <h1>Hi{user ? `, ${user.display_name}` : ''} — the guide is next</h1>
        <p>
          Your account is set up. Connecting TV sources and the colourful set-top-box guide land in
          the next phases. For now you can manage your{' '}
          <Link to="/settings" className="linkish">
            security settings
          </Link>{' '}
          — passkeys, two-factor, active sessions, and your timezone.
        </p>
      </div>
    </div>
  );
}

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
          Your account is set up.{' '}
          <Link to="/sources" className="linkish">
            Connect a source
          </Link>{' '}
          (M3U, Xtream or Stalker) to start pulling in channels — the colourful set-top-box guide
          itself arrives in a later phase. You can also manage your{' '}
          <Link to="/settings" className="linkish">
            security settings
          </Link>
          .
        </p>
      </div>
    </div>
  );
}

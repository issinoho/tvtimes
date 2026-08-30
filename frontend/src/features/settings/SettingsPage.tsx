import { PasskeysSection } from '@/features/settings/PasskeysSection';
import { SessionsSection } from '@/features/settings/SessionsSection';
import { TimezoneSection } from '@/features/settings/TimezoneSection';
import { TotpSection } from '@/features/settings/TotpSection';
import { useAuth } from '@/lib/auth/AuthProvider';
import styles from '@/features/settings/settings.module.css';

export function SettingsPage() {
  const { user } = useAuth();

  return (
    <div className={styles.page}>
      <div>
        <h1 className={styles.title}>Settings</h1>
        {user ? (
          <p className={styles.hint}>
            {user.display_name} · {user.email}
          </p>
        ) : null}
      </div>

      <PasskeysSection />
      <TotpSection />
      <SessionsSection />
      <TimezoneSection />
    </div>
  );
}

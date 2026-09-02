import { ActivityNotificationsSection } from '@/features/settings/ActivityNotificationsSection';
import { ConnectorsSection } from '@/features/settings/ConnectorsSection';
import { ExportsSection } from '@/features/settings/ExportsSection';
import { NotificationsSection } from '@/features/settings/NotificationsSection';
import { PasskeysSection } from '@/features/settings/PasskeysSection';
import { SessionsSection } from '@/features/settings/SessionsSection';
import { SourceAlertsSection } from '@/features/settings/SourceAlertsSection';
import { TimezoneSection } from '@/features/settings/TimezoneSection';
import { TmdbSection } from '@/features/settings/TmdbSection';
import { TotpSection } from '@/features/settings/TotpSection';
import { useAuth } from '@/lib/auth/AuthProvider';
import { useAppVersion } from '@/lib/version';
import styles from '@/features/settings/settings.module.css';

export function SettingsPage() {
  const { user } = useAuth();
  const { data: health } = useAppVersion();
  const version = health?.version;
  const isRelease = Boolean(version) && version !== 'dev';

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
      <TmdbSection />
      <ConnectorsSection />
      <ExportsSection />
      <SourceAlertsSection />
      <NotificationsSection />
      <ActivityNotificationsSection />

      {version ? (
        <p className={styles.version}>
          tvtimes{' '}
          {isRelease ? (
            <a
              href={`https://github.com/issinoho/tvtimes/releases/tag/v${version}`}
              target="_blank"
              rel="noreferrer noopener"
            >
              v{version}
            </a>
          ) : (
            'dev build'
          )}
        </p>
      ) : null}
    </div>
  );
}

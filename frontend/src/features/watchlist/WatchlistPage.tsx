import { fmtDayTime } from '@/features/guide/time';
import { useRemoveWatch, useWatchlist } from '@/features/watchlist/api';
import { useAuth } from '@/lib/auth/AuthProvider';
import styles from '@/features/watchlist/watchlist.module.css';

export function WatchlistPage() {
  const { user } = useAuth();
  const { data, isLoading } = useWatchlist();
  const remove = useRemoveWatch();
  const items = data?.items ?? [];

  return (
    <div className={styles.page}>
      <h1 className={styles.title}>Watchlist</h1>
      {user && !user.email_verified ? (
        <p className={styles.hint}>Verify your email to receive reminders.</p>
      ) : (
        <p className={styles.hint}>
          A reminder email goes out about 15 minutes before each airing.
        </p>
      )}

      {isLoading ? null : items.length === 0 ? (
        <p className={styles.hint}>
          Nothing here yet. Open a programme from the guide or search and choose “Remind me” or
          “Watch this title”.
        </p>
      ) : (
        <ul className={styles.list}>
          {items.map((it) => (
            <li key={it.id} className={styles.item}>
              <span className={styles.tag}>{it.kind === 'title' ? 'title' : 'airing'}</span>
              <span className={styles.body}>
                <span className={styles.name}>{it.title}</span>
                <span className={styles.meta}>
                  {it.start && it.channel_name
                    ? `${it.channel_name} · ${fmtDayTime(it.start, it.timezone ?? undefined)}`
                    : it.kind === 'title'
                      ? 'No upcoming airing in the guide'
                      : '—'}
                </span>
              </span>
              <button
                type="button"
                className={styles.btn}
                disabled={remove.isPending}
                onClick={() => remove.mutate(it.id)}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

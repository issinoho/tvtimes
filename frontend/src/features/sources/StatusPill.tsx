import styles from '@/features/sources/sources.module.css';

const LABEL: Record<string, string> = {
  ok: 'Ready',
  error: 'Error',
  pending: 'Refreshing…',
};

export function StatusPill({ status }: { status: string }) {
  const kind = status in LABEL ? status : 'pending';
  return <span className={`${styles.pill} ${styles[kind]}`}>{LABEL[kind] ?? status}</span>;
}

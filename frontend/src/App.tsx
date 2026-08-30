import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';

import { BrandLockup } from '@/components/BrandLockup';
import { getHealth } from '@/lib/api/client';
import styles from '@/App.module.css';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
});

function ApiStatus() {
  const { data, isPending, isError } = useQuery({
    queryKey: ['health'],
    queryFn: getHealth,
  });

  let label = 'checking API…';
  let tone = styles.pending;
  if (isError) {
    label = 'API unreachable';
    tone = styles.error;
  } else if (!isPending && data) {
    label = `API ok · v${data.version}`;
    tone = styles.ok;
  }
  return <span className={`${styles.status} ${tone}`}>{label}</span>;
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <main className={styles.shell}>
        <BrandLockup className={styles.logo} />
        <h1 className={styles.title}>the guide is coming</h1>
        <p className={styles.blurb}>
          A modern, multi-tenant TV schedule. Connect your sources, pick a timezone, and browse a
          colourful set-top-box guide enriched with logos and a cinematic info panel.
        </p>
        <ApiStatus />
      </main>
    </QueryClientProvider>
  );
}

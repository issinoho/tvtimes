import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { api, ApiError, unwrap } from '@/lib/api/client';
import type { components } from '@/lib/api/schema';
import styles from '@/features/settings/settings.module.css';

type Connector = components['schemas']['ConnectorOut'];

const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : 'never');

function StatusDot({ status }: { status: string }) {
  const label = { online: 'online', offline: 'offline', unpaired: 'not paired' }[status] ?? status;
  return <span className={styles.badge}>{label}</span>;
}

export function ConnectorsSection() {
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [newHint, setNewHint] = useState<{ name: string; hint: string; code: string } | null>(null);

  const { data: connectors = [] } = useQuery({
    queryKey: ['connectors'],
    queryFn: async () => unwrap(await api.GET('/api/connectors')),
    refetchInterval: (q) =>
      (q.state.data ?? []).some((c) => c.status !== 'online') ? 5000 : 15000,
  });

  const add = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST('/api/connectors', { body: { name: 'Home network' } })),
    onSuccess: (c) => {
      setNewHint({ name: c.name, hint: c.install_hint, code: c.pairing_code ?? '' });
      void qc.invalidateQueries({ queryKey: ['connectors'] });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : 'Could not add a connector.'),
  });

  const remove = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.DELETE('/api/connectors/{connector_id}', {
          params: { path: { connector_id: id } },
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['connectors'] }),
  });

  const regen = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST('/api/connectors/{connector_id}/pairing-code', {
          params: { path: { connector_id: id } },
        }),
      ),
    onSuccess: (c) => {
      setNewHint({
        name: c.name,
        hint: `…pair --code ${c.pairing_code}`,
        code: c.pairing_code ?? '',
      });
      void qc.invalidateQueries({ queryKey: ['connectors'] });
    },
  });

  return (
    <section className={styles.section}>
      <h2>Connectors</h2>
      <p className={styles.hint}>
        Run a small agent on your home network to use HDHomeRun tuners. It only makes outbound
        connections — no ports to open. See{' '}
        <a
          href="https://github.com/issinoho/tvtimes/tree/main/connector"
          className="linkish"
          target="_blank"
          rel="noreferrer noopener"
        >
          the connector README
        </a>
        .
      </p>

      {connectors.length > 0 ? (
        <ul className={styles.list}>
          {connectors.map((c: Connector) => (
            <li key={c.id} className={styles.item}>
              <span>
                {c.name}
                <StatusDot status={c.status} />
                <span className={styles.meta}>
                  {' '}
                  {c.version ? `· v${c.version} ` : ''}· last seen {fmt(c.last_seen_at)}
                  {c.devices.length ? ` · ${c.devices.length} device(s)` : ''}
                  {c.status === 'unpaired' && c.pairing_code ? ` · code ${c.pairing_code}` : ''}
                </span>
              </span>
              <span className={styles.actions} style={{ margin: 0 }}>
                {c.status === 'unpaired' ? (
                  <button type="button" className={styles.btn} onClick={() => regen.mutate(c.id)}>
                    New code
                  </button>
                ) : null}
                <button
                  type="button"
                  className={`${styles.btn} ${styles.danger}`}
                  onClick={() => {
                    if (window.confirm('Remove this connector and its channels?'))
                      remove.mutate(c.id);
                  }}
                >
                  Remove
                </button>
              </span>
            </li>
          ))}
        </ul>
      ) : null}

      <div className={styles.actions}>
        <button
          type="button"
          className={`${styles.btn} ${styles.primary}`}
          onClick={() => {
            setError(null);
            add.mutate();
          }}
          disabled={add.isPending}
        >
          Add a connector
        </button>
      </div>

      {newHint ? (
        <div className={styles.section} style={{ marginTop: '0.75rem' }}>
          <p className={styles.hint}>On your home network, install the connector and run:</p>
          <p className={styles.secret}>{newHint.hint}</p>
          <p className={styles.hint}>The pairing code expires in 15 minutes.</p>
        </div>
      ) : null}
      {error ? <p className={styles.error}>{error}</p> : null}
    </section>
  );
}

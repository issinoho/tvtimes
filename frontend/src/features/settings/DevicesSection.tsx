import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';

import { api, ApiError, unwrap } from '@/lib/api/client';
import type { components } from '@/lib/api/schema';
import styles from '@/features/settings/settings.module.css';

type Device = components['schemas']['DeviceOut'];

const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : 'never');

/**
 * TVs paired by find-and-approve: the TV shows a code, you enter it here, and
 * the TV gets its own export token -- no token to copy across. Each device can
 * be removed on its own, which stops its token at once.
 */
export function DevicesSection() {
  const qc = useQueryClient();
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  const { data: devices = [] } = useQuery({
    queryKey: ['devices'],
    queryFn: async () => unwrap(await api.GET('/api/devices')),
    // Approved but not yet collected flips to paired within seconds.
    refetchInterval: (q) => ((q.state.data ?? []).some((d) => !d.paired) ? 3000 : false),
  });

  const approve = useMutation({
    mutationFn: async (value: string) =>
      unwrap(await api.POST('/api/devices', { body: { code: value } })),
    onSuccess: (d) => {
      setCode('');
      setOk(`Approved “${d.name}”. It will finish pairing in a few seconds.`);
      void qc.invalidateQueries({ queryKey: ['devices'] });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : 'Could not approve that code.'),
  });

  const remove = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.DELETE('/api/devices/{device_id}', { params: { path: { device_id: id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['devices'] }),
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setOk(null);
    approve.mutate(code.trim());
  }

  return (
    <section className={styles.section}>
      <h2>Devices</h2>
      <p className={styles.hint}>
        Pair a TV app such as radiotimes without copying a token: choose “Pair with tvtimes” on the
        TV, then enter the code it shows. Each device gets its own feed token, which removing it
        here revokes.
      </p>

      {devices.length > 0 ? (
        <ul className={styles.list}>
          {devices.map((d: Device) => (
            <li key={d.id} className={styles.item}>
              <span>
                {d.name}
                <span className={styles.badge}>{d.paired ? 'paired' : 'finishing…'}</span>
                <span className={styles.meta}>
                  {' '}
                  · paired {fmt(d.approved_at)} · last used {fmt(d.last_used_at)}
                </span>
              </span>
              <span className={styles.actions} style={{ margin: 0 }}>
                <button
                  type="button"
                  className={`${styles.btn} ${styles.danger}`}
                  onClick={() => {
                    if (window.confirm(`Remove “${d.name}”? It will stop receiving the guide.`))
                      remove.mutate(d.id);
                  }}
                >
                  Remove
                </button>
              </span>
            </li>
          ))}
        </ul>
      ) : null}

      <form onSubmit={submit}>
        <input
          className={styles.select}
          style={{ minWidth: 200, maxWidth: '100%', letterSpacing: '0.1em' }}
          aria-label="Code shown on the TV"
          placeholder="Code on the TV"
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          value={code}
          onChange={(e) => setCode(e.target.value)}
        />
        <div className={styles.actions}>
          <button
            type="submit"
            className={`${styles.btn} ${styles.primary}`}
            disabled={approve.isPending || code.replace(/[^a-z0-9]/gi, '').length < 4}
          >
            {approve.isPending ? 'Approving…' : 'Approve'}
          </button>
        </div>
      </form>
      {ok ? <p className={styles.ok}>{ok}</p> : null}
      {error ? <p className={styles.error}>{error}</p> : null}
    </section>
  );
}

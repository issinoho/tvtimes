import { useCallback, useState } from 'react';

import { type Ink, inkOf } from '@/features/guide/logoInk';

/** A channel logo, always fetched through our origin proxy
 * (`/api/channels/{id}/logo`) so `http://` LAN / IPTV logos still load on an
 * HTTPS page — which also keeps the canvas untainted, so `inkOf` can read the
 * artwork and pick a ground that suits it. Falls back to the empty placeholder
 * when the channel has no logo or the fetch fails. */
export function ChannelLogo({
  channelId,
  hasLogo,
  imgClassName,
  emptyClassName,
}: {
  channelId: string;
  hasLogo: boolean;
  imgClassName?: string;
  emptyClassName?: string;
}) {
  const [broken, setBroken] = useState(false);
  const [ink, setInk] = useState<Ink | null>(null);

  const onLoad = useCallback((e: React.SyntheticEvent<HTMLImageElement>) => {
    setInk(inkOf(e.currentTarget));
  }, []);

  if (!hasLogo || broken) return <span className={emptyClassName} aria-hidden />;
  return (
    <img
      className={imgClassName}
      // Absent until the artwork has been read: the CSS default is a neutral
      // tile, so a logo is never unreadable while this resolves.
      data-ink={ink ?? undefined}
      src={`/api/channels/${channelId}/logo`}
      alt=""
      loading="lazy"
      onLoad={onLoad}
      onError={() => setBroken(true)}
    />
  );
}

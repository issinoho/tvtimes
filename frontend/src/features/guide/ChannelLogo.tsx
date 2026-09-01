import { useState } from 'react';

/** A channel logo, always fetched through our origin proxy
 * (`/api/channels/{id}/logo`) so `http://` LAN / IPTV logos still load on an
 * HTTPS page. Falls back to the empty placeholder when the channel has no logo
 * or the fetch fails. */
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
  if (!hasLogo || broken) return <span className={emptyClassName} aria-hidden />;
  return (
    <img
      className={imgClassName}
      src={`/api/channels/${channelId}/logo`}
      alt=""
      loading="lazy"
      onError={() => setBroken(true)}
    />
  );
}

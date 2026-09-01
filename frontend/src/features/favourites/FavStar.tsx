import { useFavourites, useToggleFavourite } from '@/features/favourites/api';
import styles from '@/features/favourites/favourites.module.css';

/** A star toggle for one channel. Stops click propagation so it can sit inside
 *  a clickable row / card. */
export function FavStar({ channelId, className }: { channelId: string; className?: string }) {
  const { data: favs } = useFavourites();
  const toggle = useToggleFavourite();
  const on = favs?.has(channelId) ?? false;

  return (
    <button
      type="button"
      className={`${styles.star}${className ? ` ${className}` : ''}`}
      data-on={on || undefined}
      aria-pressed={on}
      aria-label={on ? 'Remove channel from favourites' : 'Add channel to favourites'}
      title={on ? 'Favourite channel' : 'Add to favourites'}
      onClick={(e) => {
        e.stopPropagation();
        toggle.mutate({ channelId, on: !on });
      }}
    >
      {on ? '★' : '☆'}
    </button>
  );
}

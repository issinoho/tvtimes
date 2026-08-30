/** tvtimes wordmark + mark. See docs/brand.md. */

interface Props {
  className?: string;
  title?: string;
}

export function BrandLockup({ className, title = 'tvtimes' }: Props) {
  return (
    <svg
      className={className}
      viewBox="0 0 260 64"
      role="img"
      aria-label={title}
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <linearGradient id="tvt-grad" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#1B0A3D" />
          <stop offset="0.45" stopColor="#6D28D9" />
          <stop offset="1" stopColor="#DB2777" />
        </linearGradient>
      </defs>

      {/* mark: screen */}
      <rect x="2" y="8" width="56" height="44" rx="12" fill="url(#tvt-grad)" />
      <rect
        x="2"
        y="8"
        width="56"
        height="44"
        rx="12"
        fill="none"
        stroke="#F4EEFF"
        strokeOpacity="0.12"
      />
      {/* scanline */}
      <rect x="12" y="29" width="36" height="2" rx="1" fill="#F4EEFF" fillOpacity="0.35" />
      {/* play triangle */}
      <path d="M25 20 L41 30 L25 40 Z" fill="#F4EEFF" fillOpacity="0.92" />

      {/* wordmark */}
      <text
        x="72"
        y="41"
        fontFamily="'Space Grotesk', ui-sans-serif, system-ui, sans-serif"
        fontSize="30"
        fontWeight="600"
        letterSpacing="-0.5"
        fill="currentColor"
      >
        tvtimes
      </text>
    </svg>
  );
}

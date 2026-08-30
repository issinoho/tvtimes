import { useEffect, useState } from 'react';

const supported = () => typeof window !== 'undefined' && typeof window.matchMedia === 'function';

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    supported() ? window.matchMedia(query).matches : false,
  );

  useEffect(() => {
    if (!supported()) return;
    const mql = window.matchMedia(query);
    const onChange = () => setMatches(mql.matches);
    onChange();
    mql.addEventListener('change', onChange);
    return () => mql.removeEventListener('change', onChange);
  }, [query]);

  return matches;
}

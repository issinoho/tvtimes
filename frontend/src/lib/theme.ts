export type ThemePref = 'system' | 'light' | 'dark';

const KEY = 'tvtimes.theme';
const ORDER: ThemePref[] = ['system', 'light', 'dark'];

export function loadTheme(): ThemePref {
  try {
    const v = localStorage.getItem(KEY);
    if (v === 'light' || v === 'dark' || v === 'system') return v;
  } catch {
    /* private mode / blocked storage */
  }
  return 'system';
}

export function applyTheme(pref: ThemePref): void {
  const root = document.documentElement;
  if (pref === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', pref);
  try {
    localStorage.setItem(KEY, pref);
  } catch {
    /* ignore */
  }
}

export function nextTheme(pref: ThemePref): ThemePref {
  return ORDER[(ORDER.indexOf(pref) + 1) % ORDER.length];
}

export const THEME_LABEL: Record<ThemePref, string> = {
  system: 'Auto',
  light: 'Light',
  dark: 'Dark',
};

import { useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';

import { BrandLockup } from '@/components/BrandLockup';
import { useAuth } from '@/lib/auth/AuthProvider';
import { applyTheme, loadTheme, nextTheme, THEME_LABEL } from '@/lib/theme';
import styles from '@/features/app/AppLayout.module.css';

export function AppLayout() {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const [theme, setTheme] = useState(loadTheme);

  async function onSignOut() {
    await logout();
    navigate('/login', { replace: true });
  }

  function cycleTheme() {
    const next = nextTheme(theme);
    setTheme(next);
    applyTheme(next);
  }

  return (
    <>
      <a href="#main" className={styles.skipLink}>
        Skip to content
      </a>
      <header className={styles.header}>
        <BrandLockup />
        <nav className={styles.nav} aria-label="Main">
          <NavLink to="/" end className={styles.navLink}>
            {({ isActive }) => <span data-active={isActive}>Guide</span>}
          </NavLink>
          <NavLink to="/search" className={styles.navLink}>
            {({ isActive }) => <span data-active={isActive}>Search</span>}
          </NavLink>
          <NavLink to="/watchlist" className={styles.navLink}>
            {({ isActive }) => <span data-active={isActive}>Watchlist</span>}
          </NavLink>
          <NavLink to="/sources" className={styles.navLink}>
            {({ isActive }) => <span data-active={isActive}>Sources</span>}
          </NavLink>
          <NavLink to="/settings" className={styles.navLink}>
            {({ isActive }) => <span data-active={isActive}>Settings</span>}
          </NavLink>
          <button
            type="button"
            className={styles.signout}
            onClick={cycleTheme}
            aria-label={`Theme: ${THEME_LABEL[theme]}. Click to change.`}
            title={`Theme: ${THEME_LABEL[theme]}`}
          >
            {THEME_LABEL[theme]}
          </button>
          <button type="button" className={styles.signout} onClick={onSignOut}>
            Sign out
          </button>
        </nav>
      </header>
      <main className={styles.main} id="main">
        <Outlet />
      </main>
    </>
  );
}

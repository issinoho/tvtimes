import { NavLink, Outlet, useNavigate } from 'react-router-dom';

import { BrandLockup } from '@/components/BrandLockup';
import { useAuth } from '@/lib/auth/AuthProvider';
import styles from '@/features/app/AppLayout.module.css';

export function AppLayout() {
  const { logout } = useAuth();
  const navigate = useNavigate();

  async function onSignOut() {
    await logout();
    navigate('/login', { replace: true });
  }

  return (
    <>
      <header className={styles.header}>
        <BrandLockup />
        <nav className={styles.nav}>
          <NavLink to="/" end className={styles.navLink}>
            {({ isActive }) => <span data-active={isActive}>Guide</span>}
          </NavLink>
          <NavLink to="/sources" className={styles.navLink}>
            {({ isActive }) => <span data-active={isActive}>Sources</span>}
          </NavLink>
          <NavLink to="/settings" className={styles.navLink}>
            {({ isActive }) => <span data-active={isActive}>Settings</span>}
          </NavLink>
          <button type="button" className={styles.signout} onClick={onSignOut}>
            Sign out
          </button>
        </nav>
      </header>
      <main className={styles.main}>
        <Outlet />
      </main>
    </>
  );
}

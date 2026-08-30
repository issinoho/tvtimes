import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';

import { SKIP_PASSKEY_KEY } from '@/lib/auth/constants';
import { useAuth } from '@/lib/auth/AuthProvider';

function skippedPasskey(): boolean {
  try {
    return sessionStorage.getItem(SKIP_PASSKEY_KEY) === '1';
  } catch {
    return false;
  }
}

/**
 * Gate for authenticated routes. While the initial refresh is in flight we
 * render nothing (a flash-free splash). `stage="onboarding"` skips the
 * "add a passkey" redirect so the onboarding page itself can render.
 */
export function RequireAuth({
  children,
  stage = 'app',
}: {
  children: ReactNode;
  stage?: 'app' | 'onboarding';
}) {
  const { status, user } = useAuth();
  const location = useLocation();

  if (status === 'loading') return null;
  if (status === 'anon' || !user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  const needsPasskey = user.passkey_count === 0 && !skippedPasskey();
  if (stage === 'app' && needsPasskey) {
    return <Navigate to="/onboarding" replace />;
  }
  if (stage === 'onboarding' && !needsPasskey) {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}

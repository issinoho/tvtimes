import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import {
  api,
  ApiError,
  refreshAccessToken,
  setAccessToken,
  setAuthLostHandler,
  unwrap,
} from '@/lib/api/client';
import { getPasskeyAssertion } from '@/lib/auth/webauthn';
import type { AuthStatus, Me, MfaChallenge } from '@/lib/auth/types';

interface AuthContextValue {
  status: AuthStatus;
  user: Me | null;
  refreshMe: () => Promise<void>;
  loginWithPassword: (email: string, password: string) => Promise<MfaChallenge | null>;
  completeMfa: (mfaToken: string, code: string) => Promise<void>;
  loginWithPasskey: (email?: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [user, setUser] = useState<Me | null>(null);
  const booted = useRef(false);

  const refreshMe = useCallback(async () => {
    const me = unwrap(await api.GET('/api/account/me'));
    setUser(me);
    setStatus('authed');
  }, []);

  const goAnon = useCallback(() => {
    setAccessToken(null);
    setUser(null);
    setStatus('anon');
  }, []);

  useEffect(() => {
    setAuthLostHandler(goAnon);
  }, [goAnon]);

  useEffect(() => {
    if (booted.current) return;
    booted.current = true;
    void (async () => {
      const ok = await refreshAccessToken();
      if (!ok) {
        goAnon();
        return;
      }
      try {
        await refreshMe();
      } catch {
        goAnon();
      }
    })();
  }, [goAnon, refreshMe]);

  const loginWithPassword = useCallback(
    async (email: string, password: string): Promise<MfaChallenge | null> => {
      const result = await api.POST('/api/auth/login', { body: { email, password } });
      if (result.error) {
        const err = result.error as { code?: string; mfa_token?: string; message?: string };
        if (err.code === 'mfa_required' && err.mfa_token) {
          return { mfaToken: err.mfa_token };
        }
        throw new ApiError(
          result.response.status,
          err.code ?? 'error',
          err.message ?? 'Login failed',
        );
      }
      setAccessToken(result.data.access_token);
      await refreshMe();
      return null;
    },
    [refreshMe],
  );

  const completeMfa = useCallback(
    async (mfaToken: string, code: string) => {
      const token = unwrap(
        await api.POST('/api/auth/login/mfa', { body: { mfa_token: mfaToken, code } }),
      );
      setAccessToken(token.access_token);
      await refreshMe();
    },
    [refreshMe],
  );

  const loginWithPasskey = useCallback(
    async (email?: string) => {
      const options = unwrap(
        await api.POST('/api/auth/webauthn/login/options', {
          body: email ? { email } : {},
        }),
      );
      const assertion = await getPasskeyAssertion(options.options);
      const token = unwrap(
        await api.POST('/api/auth/webauthn/login/verify', {
          body: { credential: assertion as Record<string, unknown> },
        }),
      );
      setAccessToken(token.access_token);
      await refreshMe();
    },
    [refreshMe],
  );

  const logout = useCallback(async () => {
    try {
      await api.POST('/api/auth/logout');
    } finally {
      goAnon();
    }
  }, [goAnon]);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      user,
      refreshMe,
      loginWithPassword,
      completeMfa,
      loginWithPasskey,
      logout,
    }),
    [status, user, refreshMe, loginWithPassword, completeMfa, loginWithPasskey, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components -- provider + its hook live together
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within <AuthProvider>');
  return ctx;
}

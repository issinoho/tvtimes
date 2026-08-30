import type { components } from '@/lib/api/schema';

export type Me = components['schemas']['MeOut'];
export type TokenOut = components['schemas']['TokenOut'];

export type AuthStatus = 'loading' | 'authed' | 'anon';

export interface MfaChallenge {
  mfaToken: string;
}

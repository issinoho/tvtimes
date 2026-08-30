import { api, unwrap } from '@/lib/api/client';
import { createPasskey } from '@/lib/auth/webauthn';

/** Register a passkey for the signed-in user (onboarding + settings). */
export async function registerPasskey(nickname: string): Promise<void> {
  const options = unwrap(await api.POST('/api/account/passkeys/options'));
  const credential = await createPasskey(options.options);
  unwrap(
    await api.POST('/api/account/passkeys', {
      body: { credential: credential as Record<string, unknown>, nickname },
    }),
  );
}

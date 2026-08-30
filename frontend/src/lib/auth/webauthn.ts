/**
 * Passkey ceremony helpers. The backend hands us the raw JSON string from
 * py_webauthn's `options_to_json()`; @simplewebauthn/browser expects the parsed
 * object and returns the credential JSON we post straight back.
 */

import {
  startAuthentication,
  startRegistration,
  type PublicKeyCredentialCreationOptionsJSON,
  type PublicKeyCredentialRequestOptionsJSON,
} from '@simplewebauthn/browser';

export function browserSupportsPasskeys(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.PublicKeyCredential !== 'undefined' &&
    typeof navigator.credentials !== 'undefined'
  );
}

export async function createPasskey(optionsJson: string): Promise<unknown> {
  const optionsJSON = JSON.parse(optionsJson) as PublicKeyCredentialCreationOptionsJSON;
  return startRegistration({ optionsJSON });
}

export async function getPasskeyAssertion(
  optionsJson: string,
  { conditional = false }: { conditional?: boolean } = {},
): Promise<unknown> {
  const optionsJSON = JSON.parse(optionsJson) as PublicKeyCredentialRequestOptionsJSON;
  return startAuthentication({ optionsJSON, useBrowserAutofill: conditional });
}

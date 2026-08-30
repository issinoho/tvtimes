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

function hasWebAuthnApi(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.PublicKeyCredential !== 'undefined' &&
    typeof navigator.credentials !== 'undefined'
  );
}

/** The WebAuthn API exists but the page isn't a secure context (plain HTTP on a
 * LAN IP) — the ceremony would throw. `localhost` and HTTPS are fine. */
export function passkeysNeedSecureContext(): boolean {
  return hasWebAuthnApi() && typeof window !== 'undefined' && window.isSecureContext === false;
}

export function browserSupportsPasskeys(): boolean {
  return hasWebAuthnApi() && (typeof window === 'undefined' || window.isSecureContext !== false);
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

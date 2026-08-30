/**
 * Passkey ceremony helpers. The backend hands us the raw JSON string from
 * py_webauthn's `options_to_json()`; @simplewebauthn/browser expects the parsed
 * object and returns the credential JSON we post straight back.
 */

import {
  startAuthentication,
  startRegistration,
  WebAuthnError,
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

/**
 * Turn a failed passkey ceremony into an actionable message. The most common
 * self-hosting failure is an RP-ID / origin mismatch, which the browser rejects
 * before any prompt — so spell out exactly what the two env vars should be.
 */
export function describePasskeyError(err: unknown): string {
  const loc = typeof window !== 'undefined' ? window.location : null;
  const config = loc
    ? ` Set TVTIMES_WEBAUTHN_RP_ID="${loc.hostname}" and TVTIMES_PUBLIC_ORIGIN="${loc.origin}", then restart tvtimes.`
    : '';

  const code = err instanceof WebAuthnError ? err.code : '';
  const name = err instanceof DOMException ? err.name : '';

  if (code === 'ERROR_INVALID_RP_ID' || code === 'ERROR_INVALID_DOMAIN' || name === 'SecurityError')
    return `This site's passkey settings don't match its address.${config}`;
  if (code === 'ERROR_CEREMONY_ABORTED' || name === 'NotAllowedError' || name === 'AbortError')
    return 'The request was cancelled or timed out — try again and approve the prompt.';
  if (code === 'ERROR_AUTHENTICATOR_PREVIOUSLY_REGISTERED' || name === 'InvalidStateError')
    return 'This device already has a passkey for your account.';
  if (name === 'NotSupportedError')
    return 'This device has no authenticator that meets the requirements.';

  const detail = err instanceof Error && err.message ? `: ${err.message}` : '';
  return `Passkey setup failed${detail}.`;
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

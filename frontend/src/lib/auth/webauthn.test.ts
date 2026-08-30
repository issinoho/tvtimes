import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  browserSupportsPasskeys,
  describePasskeyError,
  passkeysNeedSecureContext,
} from './webauthn';

function setContext({ api, secure }: { api: boolean; secure: boolean }) {
  if (api) {
    vi.stubGlobal('PublicKeyCredential', function PublicKeyCredential() {});
    Object.defineProperty(navigator, 'credentials', { value: {}, configurable: true });
  } else {
    vi.stubGlobal('PublicKeyCredential', undefined);
  }
  Object.defineProperty(window, 'isSecureContext', { value: secure, configurable: true });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('passkey environment checks', () => {
  it('usable only when the API exists and the context is secure', () => {
    setContext({ api: true, secure: true });
    expect(browserSupportsPasskeys()).toBe(true);
    expect(passkeysNeedSecureContext()).toBe(false);
  });

  it('flags an insecure context (HTTP on a LAN IP) rather than claiming no support', () => {
    setContext({ api: true, secure: false });
    expect(browserSupportsPasskeys()).toBe(false);
    expect(passkeysNeedSecureContext()).toBe(true);
  });

  it('no WebAuthn API at all is just unsupported', () => {
    setContext({ api: false, secure: false });
    expect(browserSupportsPasskeys()).toBe(false);
    expect(passkeysNeedSecureContext()).toBe(false);
  });
});

describe('describePasskeyError', () => {
  it('an RP-ID / SecurityError names the exact env vars to set', () => {
    Object.defineProperty(window, 'location', {
      value: { hostname: 'tv.example.com', origin: 'https://tv.example.com' },
      configurable: true,
    });
    const msg = describePasskeyError(new DOMException('bad rp id', 'SecurityError'));
    expect(msg).toContain('TVTIMES_WEBAUTHN_RP_ID="tv.example.com"');
    expect(msg).toContain('TVTIMES_PUBLIC_ORIGIN="https://tv.example.com"');
  });

  it('a cancelled ceremony reads as cancelled, not a config error', () => {
    const msg = describePasskeyError(new DOMException('aborted', 'NotAllowedError'));
    expect(msg.toLowerCase()).toContain('cancelled');
    expect(msg).not.toContain('TVTIMES_');
  });

  it('falls back to the error message', () => {
    expect(describePasskeyError(new Error('boom'))).toBe('Passkey setup failed: boom.');
  });
});

import { afterEach, describe, expect, it, vi } from 'vitest';

import { browserSupportsPasskeys, passkeysNeedSecureContext } from './webauthn';

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

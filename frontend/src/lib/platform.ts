/** Coarse platform checks. Only used to pick a hand-off mechanism for
 *  "Play externally" (Android gets an intent:// app chooser; everything else
 *  gets a .m3u download). Not for feature gating. */
export const isAndroid = (): boolean =>
  typeof navigator !== 'undefined' && /Android/i.test(navigator.userAgent);

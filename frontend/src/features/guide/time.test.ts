import { describe, expect, it } from 'vitest';

import { fmtDayTime, fmtTime, formatRange } from './time';

// 20:45 in New York (EDT, -04:00) == 01:45 the next day in London (BST, +01:00).
const NY_EVENING = '2026-08-30T20:45:00-04:00';

describe('guide time formatting', () => {
  it('renders an instant in the channel timezone, not the viewer local one', () => {
    expect(fmtTime(NY_EVENING, 'America/New_York')).toBe('20:45');
    expect(fmtTime(NY_EVENING, 'Europe/London')).toBe('01:45');
    expect(fmtTime(NY_EVENING, 'UTC')).toBe('00:45');
  });

  it('fmtDayTime includes the weekday in the given zone', () => {
    expect(fmtDayTime(NY_EVENING, 'America/New_York')).toMatch(/^Sun,? 20:45$/);
    // Past midnight in London, so the weekday rolls over.
    expect(fmtDayTime(NY_EVENING, 'Europe/London')).toMatch(/^Mon,? 01:45$/);
  });

  it('formatRange pairs start and stop in one zone', () => {
    expect(formatRange(NY_EVENING, '2026-08-30T22:15:00-04:00', 'America/New_York')).toBe(
      '20:45 – 22:15',
    );
  });
});

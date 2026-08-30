export const PX_PER_MIN = 4;
export const ROW_H = 60;
export const COL_W = 190;
export const AXIS_H = 40;
export const WINDOW_MINUTES = 6 * 60;

export const minutesBetween = (a: Date, b: Date) => (b.getTime() - a.getTime()) / 60_000;
export const xOf = (from: Date, at: Date) => minutesBetween(from, at) * PX_PER_MIN;
export const trackWidth = () => WINDOW_MINUTES * PX_PER_MIN;

export function startOfHour(d: Date): Date {
  const c = new Date(d);
  c.setMinutes(0, 0, 0);
  return c;
}

export function defaultWindowStart(now = new Date()): Date {
  return new Date(startOfHour(now).getTime() - 60 * 60_000);
}

/** Half-hour tick marks across the window, labelled in `timezone`. */
export function hourTicks(from: Date, timezone: string): { x: number; label: string }[] {
  const fmt = new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: timezone,
  });
  const ticks: { x: number; label: string }[] = [];
  for (let m = 0; m <= WINDOW_MINUTES; m += 30) {
    ticks.push({ x: m * PX_PER_MIN, label: fmt.format(new Date(from.getTime() + m * 60_000)) });
  }
  return ticks;
}

/**
 * Wall-clock time of an instant, rendered in `timezone` (the channel's display
 * zone) so cards, the axis and the now-line all agree. Without a zone it falls
 * back to the viewer's local time.
 */
export function fmtTime(iso: string | Date, timezone?: string): string {
  return new Date(iso).toLocaleTimeString('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    ...(timezone ? { timeZone: timezone } : {}),
  });
}

export function fmtDayTime(iso: string | Date, timezone?: string): string {
  return new Date(iso).toLocaleString('en-GB', {
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    ...(timezone ? { timeZone: timezone } : {}),
  });
}

export function formatRange(startIso: string, stopIso: string, timezone?: string): string {
  return `${fmtTime(startIso, timezone)} – ${fmtTime(stopIso, timezone)}`;
}

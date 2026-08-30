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

export function formatRange(startIso: string, stopIso: string): string {
  const opt: Intl.DateTimeFormatOptions = { hour: '2-digit', minute: '2-digit', hour12: false };
  const s = new Date(startIso).toLocaleTimeString([], opt);
  const e = new Date(stopIso).toLocaleTimeString([], opt);
  return `${s} – ${e}`;
}

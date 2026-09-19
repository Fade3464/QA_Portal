import dayjs, { type ConfigType, type Dayjs } from 'dayjs';
import timezone from 'dayjs/plugin/timezone';
import utc from 'dayjs/plugin/utc';

dayjs.extend(utc);
dayjs.extend(timezone);

export const APP_TIME_ZONE = import.meta.env.VITE_APP_TIME_ZONE || 'America/New_York';
export const APP_TIME_ZONE_LABEL = 'Eastern Time (New York)';

/** Render an instant in the application timezone, never the browser timezone. */
export function appDate(value?: ConfigType): Dayjs {
  return value === undefined ? dayjs().tz(APP_TIME_ZONE) : dayjs(value).tz(APP_TIME_ZONE);
}

/** Parse a date-only calendar value without allowing UTC conversion to shift it. */
export function appCalendarDate(value: string): Dayjs {
  return dayjs.tz(value, APP_TIME_ZONE);
}

/** Convert a date-picker wall time to an unambiguous instant for the API. */
export function appWallTimeToIso(value: Dayjs): string {
  return dayjs.tz(value.format('YYYY-MM-DD HH:mm:ss'), APP_TIME_ZONE).toISOString();
}

/** Detect wall times skipped by the spring-forward DST transition. */
export function isValidAppWallTime(value: Dayjs): boolean {
  const wallTime = value.format('YYYY-MM-DD HH:mm:ss');
  return dayjs.tz(wallTime, APP_TIME_ZONE).format('YYYY-MM-DD HH:mm:ss') === wallTime;
}

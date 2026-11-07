/** `datetime-local` value, or an empty string when the instant is missing. */
export function toDatetimeLocal(value: string | null): string {
  if (!value) {
    return '';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '';
  }
  const pad = (part: number) => String(part).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/**
 * Keep the typed wall clock and attach the browser's offset.
 * The server writes that wall clock into EXIF and sends the instant to Immich.
 */
export function fromDatetimeLocal(value: string): string | null {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  const [day, time] = value.split('T');
  if (!day || !time) {
    return null;
  }
  const clock = time.length === 5 ? `${time}:00` : time;
  const offsetMinutes = -date.getTimezoneOffset();
  const sign = offsetMinutes >= 0 ? '+' : '-';
  const absolute = Math.abs(offsetMinutes);
  const hours = String(Math.floor(absolute / 60)).padStart(2, '0');
  const minutes = String(absolute % 60).padStart(2, '0');
  return `${day}T${clock}${sign}${hours}:${minutes}`;
}

/** DD/MM/YYYY date and optional time from a stored instant. */
export function toDateAndTime(value: string | null): { date: string; time: string } {
  const local = toDatetimeLocal(value);
  if (!local) {
    return { date: '', time: '' };
  }
  const [date, time] = local.split('T');
  const [year, month, day] = date.split('-');
  return { date: `${day}/${month}/${year}`, time: time ?? '' };
}

/**
 * A DD/MM/YYYY date can be saved without a time. A blank time is midnight on that date.
 * A blank date clears the instant, even if a time is filled in.
 */
export function fromDateAndTime(date: string, time: string): string | null {
  const value = date.trim();
  if (!value) {
    return null;
  }
  const match = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(value);
  if (!match) {
    return null;
  }
  const [, day, month, year] = match;
  const calendar = new Date(`${year}-${month}-${day}T00:00:00Z`);
  if (
    Number.isNaN(calendar.getTime()) ||
    calendar.getUTCFullYear() !== Number(year) ||
    calendar.getUTCMonth() + 1 !== Number(month) ||
    calendar.getUTCDate() !== Number(day)
  ) {
    return null;
  }
  const clock = time.trim() || '00:00';
  return fromDatetimeLocal(`${year}-${month}-${day}T${clock}`);
}

export function formatStamp(value: string | null): string {
  if (!value) {
    return '';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

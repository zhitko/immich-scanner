import { fromDateAndTime, fromDatetimeLocal, toDateAndTime, toDatetimeLocal } from './time';

describe('taken-at conversion', () => {
  it('keeps the typed wall clock and the same instant', () => {
    const result = fromDatetimeLocal('1999-01-02T03:04');
    expect(result?.startsWith('1999-01-02T03:04:00')).toBe(true);
    expect(result).toMatch(/[+-]\d{2}:\d{2}$/);
    expect(new Date(result!).getTime()).toBe(new Date('1999-01-02T03:04').getTime());
  });

  it('round-trips through the local field', () => {
    const stored = fromDatetimeLocal('1999-01-02T03:04');
    expect(toDatetimeLocal(stored)).toBe('1999-01-02T03:04');
  });

  it('clears an empty field', () => {
    expect(fromDatetimeLocal('')).toBeNull();
    expect(toDatetimeLocal(null)).toBe('');
  });

  it('saves a date without a time as midnight', () => {
    const result = fromDateAndTime('1966-12-15', '');
    expect(result?.startsWith('1966-12-15T00:00:00')).toBe(true);
    expect(toDateAndTime(result)).toEqual({ date: '1966-12-15', time: '00:00' });
  });

  it('keeps a date and a time together', () => {
    const result = fromDateAndTime('1966-12-15', '14:30');
    expect(result?.startsWith('1966-12-15T14:30:00')).toBe(true);
    expect(toDateAndTime(result)).toEqual({ date: '1966-12-15', time: '14:30' });
  });

  it('clears the instant when the date is empty', () => {
    expect(fromDateAndTime('', '14:30')).toBeNull();
    expect(fromDateAndTime('  ', '')).toBeNull();
    expect(toDateAndTime(null)).toEqual({ date: '', time: '' });
  });
});

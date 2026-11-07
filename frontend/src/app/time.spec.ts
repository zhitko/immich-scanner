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
    const result = fromDateAndTime('15/12/1966', '');
    expect(result?.startsWith('1966-12-15T00:00:00')).toBe(true);
    expect(toDateAndTime(result)).toEqual({ date: '15/12/1966', time: '00:00' });
  });

  it('keeps a date and a time together', () => {
    const result = fromDateAndTime('15/12/1966', '14:30');
    expect(result?.startsWith('1966-12-15T14:30:00')).toBe(true);
    expect(toDateAndTime(result)).toEqual({ date: '15/12/1966', time: '14:30' });
  });

  it('interprets ambiguous dates as day/month/year', () => {
    const result = fromDateAndTime('02/01/1999', '03:04');
    expect(result?.startsWith('1999-01-02T03:04:00')).toBe(true);
    expect(toDateAndTime(result)).toEqual({ date: '02/01/1999', time: '03:04' });
  });

  it('accepts leap days only in leap years', () => {
    expect(fromDateAndTime('29/02/2000', '')?.startsWith('2000-02-29T')).toBe(true);
    expect(fromDateAndTime('29/02/1900', '')).toBeNull();
    expect(fromDateAndTime('29/02/2023', '')).toBeNull();
  });

  it.each([
    '31/04/2024',
    '00/01/2024',
    '01/13/2024',
    '12/15/1966',
    '1966-12-15',
    '1/2/2024',
    'invalid',
  ])('rejects invalid or incorrectly formatted date %s', (date) =>
    expect(fromDateAndTime(date, '')).toBeNull(),
  );

  it('trims surrounding whitespace', () => {
    expect(fromDateAndTime(' 15/12/1966 ', ' 14:30 ')?.startsWith('1966-12-15T14:30:00')).toBe(
      true,
    );
  });

  it('clears the instant when the date is empty', () => {
    expect(fromDateAndTime('', '14:30')).toBeNull();
    expect(fromDateAndTime('  ', '')).toBeNull();
    expect(toDateAndTime(null)).toEqual({ date: '', time: '' });
  });
});

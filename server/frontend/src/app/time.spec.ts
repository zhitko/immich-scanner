import { fromDatetimeLocal, toDatetimeLocal } from './time';

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
});

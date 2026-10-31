import { describe, expect, it } from 'vitest';
import { nextDeclarableYear, yearProblem } from './declaredYears';

describe('declared years', () => {
  it('offers the most recent campaign not yet declared', () => {
    expect(nextDeclarableYear(2027, {})).toBe(2026);
    expect(nextDeclarableYear(2027, { '2026': 3000 })).toBe(2025);
    expect(nextDeclarableYear(2027, { '2025': 3000 })).toBe(2026);
    expect(nextDeclarableYear(2027, { '2026': 1, '2025': 1 })).toBe(2024);
  });
  it('accepts a past year with a positive yield', () => {
    expect(yearProblem(2027, {}, 2026, 3000)).toBeNull();
  });
  it('refuses a duplicate, a year that is not past, and an empty or non-positive yield', () => {
    expect(yearProblem(2027, { '2026': 3000 }, 2026, 3000)).toBe('duplicate');
    expect(yearProblem(2027, {}, 2027, 3000)).toBe('future');
    expect(yearProblem(2027, {}, 2026, null)).toBe('yield');
    expect(yearProblem(2027, {}, 2026, 0)).toBe('yield');
    expect(yearProblem(2027, {}, 1999, 5)).toBe('year');
  });
});

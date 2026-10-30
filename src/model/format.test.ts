import { expect, it } from 'vitest';
import { formatDate, formatHa, formatKgHa, formatMgKg, formatPct, pdfLang } from './format';

it('kg/ha is whole', () => {
  expect(formatKgHa(141.6, 'es')).toBe('142');
  expect(formatKgHa(1234, 'en')).toBe('1,234');
  expect(formatKgHa(null, 'es')).toBe('—');
});
it('percent and hectares have one decimal', () => {
  expect(formatPct(18.04, 'es')).toBe('18,0');
  expect(formatHa(24.64, 'en')).toBe('24.6');
});
it('mg/kg is whole', () => expect(formatMgKg(12.4, 'es')).toBe('12'));
it('dates follow the language', () => {
  expect(formatDate('2026-10-14', 'es')).toBe('14/10/2026');
  expect(formatDate('2026-10-14', 'en')).toBe('10/14/2026');
  expect(formatDate(null, 'es')).toBe('—');
});
it('the PDF is Spanish unless the language is English', () => {
  expect(pdfLang('en-GB')).toBe('en');
  expect(pdfLang('eu')).toBe('es');
});

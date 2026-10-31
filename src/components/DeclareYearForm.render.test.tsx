import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

vi.mock('@nekazari/sdk', async () => {
  const { esT } = await import('../test/esT');
  return { useTranslation: () => ({ t: esT, i18n: { language: 'es' } }), i18n: {} };
});

import { DeclareYearForm } from './DeclareYearForm';

const noop = () => undefined;
const html = (declared: Record<string, number>, initial: { year?: string; kg?: string }) =>
  renderToStaticMarkup(<DeclareYearForm campaign={2027} declared={declared} onAdd={noop} initial={initial} />);
const addDisabled = (h: string) => {
  const attrs = /<button([^>]*)>(?:<[^>]+>)*Añadir/.exec(h)?.[1] ?? '';
  return /\sdisabled(=""|\s|$)/.test(attrs);
};

describe('DeclareYearForm (es)', () => {
  it('prefills the most recent undeclared year and shows the unit', () => {
    const h = html({ '2026': 3000 }, { year: '2025' });
    expect(h).toContain('value="2025"');
    expect(h).toContain('placeholder="kg/ha (grano en fresco)"');
  });
  it('proposes campaign-1 first, through the component default', () => {
    const h = renderToStaticMarkup(<DeclareYearForm campaign={2027} declared={{}} onAdd={noop} initial={{}} />);
    expect(h).toContain('value="2026"');
  });
  it('Añadir is disabled until the yield is valid, then enabled', () => {
    expect(addDisabled(html({}, { year: '2026', kg: '' }))).toBe(true);
    expect(addDisabled(html({}, { year: '2026', kg: '0' }))).toBe(true);
    expect(addDisabled(html({}, { year: '2026', kg: '3200' }))).toBe(false);
  });
  it('refuses a year that is already declared', () => {
    const h = html({ '2026': 3000 }, { year: '2026', kg: '3200' });
    expect(addDisabled(h)).toBe(true);
    expect(h).toContain('Ese año ya está declarado.');
  });
});

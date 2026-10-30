import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

vi.mock('@nekazari/sdk', async () => {
  const { esT } = await import('../test/esT');
  return { useTranslation: () => ({ t: esT, i18n: { language: 'es' } }), i18n: {} };
});

import { FastApiError } from '../api/client';
import { ErrorBanner } from './ErrorBanner';
import { ModuleFooter } from './ModuleFooter';
import { PdfButton } from './PdfButton';
import { SourcedValue } from './ProvenanceChip';
import { StateBadge } from './StateBadge';

describe('common pieces (es)', () => {
  it('a missing value is a dash with the missing chip, never 0', () => {
    const html = renderToStaticMarkup(
      <SourcedValue value={{ value: null, provenance: 'missing', source: 'soil', note: null }} format={(v) => String(v)} />);
    expect(html).toContain('✕ falta');
    expect(html).toContain('>—<');
    expect(html).not.toContain('>0<');
  });

  it('a known value is shown with its chip', () => {
    const html = renderToStaticMarkup(
      <SourcedValue value={{ value: 142, provenance: 'measured', source: 'x', note: null }} format={(v) => String(v)} unit="kg/ha" />);
    expect(html).toContain('142 kg/ha');
    expect(html).toContain('● medido');
  });

  it('a 503 names the source and says the plan did not change', () => {
    const e = new FastApiError(503, { error: 'source_unavailable', source: 'broker', detail: 'x' });
    const html = renderToStaticMarkup(<ErrorBanner error={e} planState="draft" onRetry={() => undefined} />);
    expect(html).toContain('role="alert"');
    expect(html).toContain('No se pudo calcular: no responde la plataforma (parcelas)');
    expect(html).toContain('El plan sigue «Borrador»');
    expect(html).toContain('Reintentar');
  });

  it('a source without a translation is shown raw, not hidden', () => {
    const e = new FastApiError(503, { error: 'source_unavailable', source: 'new-thing' });
    expect(renderToStaticMarkup(<ErrorBanner error={e} />)).toContain('new_thing');
  });

  it('a session error says to reload', () => {
    expect(renderToStaticMarkup(<ErrorBanner error={new FastApiError(401, null)} />)).toContain('Sesión caducada');
  });

  it('the state badge uses the state word', () => {
    expect(renderToStaticMarkup(<StateBadge state="signed" />)).toContain('Firmado');
    expect(renderToStaticMarkup(<StateBadge state="superseded" />)).toContain('line-through');
  });

  it('the PDF button is busy while generating', () => {
    expect(renderToStaticMarkup(<PdfButton planId="p" lang="es" initialBusy />)).toContain('aria-busy="true"');
  });

  it('the footer carries the licence and the source link', () => {
    const html = renderToStaticMarkup(<ModuleFooter />);
    expect(html).toContain('AGPL-3.0');
    expect(html).toContain('https://github.com/nkz-os/nkz-module-fast-navigator');
    expect(html).toContain('FertiliCalc');
  });
});

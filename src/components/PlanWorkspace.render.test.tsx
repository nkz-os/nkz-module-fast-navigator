import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

let roles: string[] = ['Farmer'];
vi.mock('@nekazari/sdk', async () => {
  const { esT } = await import('../test/esT');
  return {
    useTranslation: () => ({ t: esT, i18n: { language: 'es' } }),
    useAuth: () => ({ hasRole: (r: string) => roles.includes(r) }),
    i18n: {},
  };
});
vi.mock('react-router-dom', () => ({ useSearchParams: () => [new URLSearchParams('campaign=2027&plan=plan-1'), vi.fn()] }));

import { FastApiError } from '../api/client';
import type { Plan } from '../api/types';
import { makePlan, makeSheet, PARCELS } from '../test/builders';

let planState: { data: Plan | null; error: unknown } = { data: null, error: null };
// The plan is loaded by [planId], the parcels by [campaign number], a crop name by [code, language].
vi.mock('../hooks/useCrops', async () => {
  const fx = await import('../test/fixtures/source-crops.json');
  return { useCrops: () => ({ data: fx.crops, error: null, loading: false, retry: () => undefined }) };
});
vi.mock('../hooks/useLoad', () => ({
  useLoad: (_load: unknown, deps: unknown[]) => {
    const retry = vi.fn();
    if (deps.length === 1 && typeof deps[0] === 'string') return { data: planState.data, error: planState.error, loading: false, retry };
    if (typeof deps[0] === 'number') return { data: PARCELS, error: null, loading: false, retry };
    return { data: 'Trigo blando', error: null, loading: false, retry };
  },
}));

import { PlanWorkspace } from './PlanWorkspace';

const render = (plan: Plan | null, extra: { initial?: { calcError?: unknown } } = {}, error: unknown = null) => {
  planState = { data: plan, error };
  return renderToStaticMarkup(<PlanWorkspace planId="plan-1" campaign={2027} {...extra} />);
};
const countOf = (html: string, text: string) => html.split(`>${text}<`).length - 1;

describe('PlanWorkspace (es)', () => {
  it('a stale draft says so and offers one primary button', () => {
    roles = ['TenantAdmin'];
    const html = render(makePlan({ calc_fresh: false }));
    expect(html).toContain('Datos cambiados: recalcula');
    expect(countOf(html, 'Recalcular')).toBe(1);
    expect(countOf(html, 'Calcular')).toBe(0);
  });

  it('a draft that was never calculated offers Calcular', () => {
    roles = ['TenantAdmin'];
    const html = render(makePlan({ sheets: [makeSheet({ result: null })] }));
    expect(countOf(html, 'Calcular')).toBe(1);
  });

  it('a fresh calculated plan has no calculate button', () => {
    roles = ['TenantAdmin'];
    const html = render(makePlan({ state: 'calculated' }));
    expect(html).not.toContain('>Calcular<');
    expect(html).not.toContain('>Recalcular<');
  });

  it('in review the holder reads only; the technician can still calculate', () => {
    roles = ['TenantAdmin'];
    const holder = render(makePlan({ state: 'in_review', calc_fresh: false }));
    expect(holder).toContain('En revisión por el técnico');
    expect(holder).not.toContain('>Recalcular<');
    roles = ['TechnicalConsultant'];
    expect(render(makePlan({ state: 'in_review', calc_fresh: false }))).toContain('>Recalcular<');
  });

  it('a field worker reads: no calculate or add-sheet buttons even on a stale draft', () => {
    roles = ['Farmer'];
    const html = render(makePlan({ calc_fresh: false }));
    expect(html).not.toContain('>Recalcular<');
    expect(html).not.toContain('>Calcular<');
    expect(html).not.toContain('+ hoja');
    expect(html).toContain('Datos cambiados: recalcula');
  });

  it('a signed plan shows who signed, when, and 12 characters of the fingerprint', () => {
    roles = ['TenantAdmin'];
    const html = render(makePlan({
      state: 'signed', signed_at: '2026-10-14T09:00:00+00:00', snapshot_sha256: 'abcdef0123456789abcdef',
      signature: { kind: 'advisor', name: 'Ana Pérez', registration_number: '1234', signed_at: '2026-10-14T09:00:00+00:00' },
    }));
    expect(html).toContain('Firmado por Ana Pérez (1234)');
    expect(html).toContain('huella abcdef012345');
    expect(html).not.toContain('abcdef0123456');
  });

  it('has the Data and Needs tabs only', () => {
    roles = ['TenantAdmin'];
    const html = render(makePlan());
    expect(html).toContain('>Datos<');
    expect(html).toContain('>Necesidades<');
    expect(html).not.toContain('Calendario');
  });

  it('a plan that does not exist sends back to the list', () => {
    const html = render(null, {}, new FastApiError(404, { error: 'not_found', detail: 'plan x' }));
    expect(html).toContain('El plan no existe.');
    expect(html).toContain('Planes');
    expect(html).not.toContain('Reintentar');
  });

  it('a failed calculation names the source, says the plan stays, and keeps the numbers', () => {
    roles = ['TenantAdmin'];
    const err = new FastApiError(503, { error: 'source_unavailable', source: 'bioorch', detail: 'x' });
    const html = render(makePlan({ calc_fresh: false }), { initial: { calcError: err } });
    expect(html).toContain('No se pudo calcular: no responde BioOrch (coeficientes de cultivo)');
    expect(html).toContain('El plan sigue «Borrador»');
    expect(html).toMatch(/N \d+–\d+ kg\/ha/);
  });

  it('counts the findings of the plan', () => {
    roles = ['TenantAdmin'];
    const f = (severity: 'block' | 'warn') => ({ rule_id: 'r', severity, params: {} });
    const html = render(makePlan({ findings: [f('block'), f('block'), f('warn')] }));
    expect(html).toContain('2 bloquean');
    expect(html).toContain('1 aviso');
  });
});

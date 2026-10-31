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
vi.mock('react-router-dom', () => ({ useSearchParams: () => [new URLSearchParams(), vi.fn()] }));

let loaded: { data: unknown; error: unknown; loading: boolean } = { data: [], error: null, loading: false };
vi.mock('../hooks/useLoad', () => ({ useLoad: () => ({ ...loaded, retry: vi.fn() }) }));

import { FastApiError } from '../api/client';
import type { PlanListItem } from '../api/types';
import { formatDate } from '../model/format';
import { afterCreateConflict, PlansList } from './PlansList';

const plan = (over: Partial<PlanListItem>): PlanListItem => ({
  id: 'p1', farm: 'tenant', campaign: 2027, version: 1, state: 'draft', row_version: 3, calc_fresh: true,
  updated_at: null, findings: { block: 0, warn: 0, info: 0 }, sheets_count: 2, signed_at: null, ...over,
});
const render = (campaign = 2027) => renderToStaticMarkup(<PlansList campaign={campaign} onOpen={() => undefined} />);

describe('PlansList (es)', () => {
  it('shows findings, a stale calculation and the open button of a draft', () => {
    roles = ['Farmer'];
    loaded = { data: [plan({ findings: { block: 2, warn: 1, info: 0 }, calc_fresh: false })], error: null, loading: false };
    const html = render();
    for (const text of ['2 bloquean', '1 aviso', 'sin recalcular', 'Borrador', 'Abrir']) expect(html).toContain(text);
  });

  it('shows the signature date and the PDF button of a signed plan', () => {
    loaded = { data: [plan({ state: 'signed', signed_at: '2026-10-14T09:00:00+00:00', version: 2 })], error: null, loading: false };
    const html = render();
    expect(html).toContain('Firmado');
    expect(html).toContain(formatDate('2026-10-14T09:00:00+00:00', 'es'));
    expect(html).toContain('>PDF<');
  });

  it('offers to create the plan to the holder and the technician', () => {
    loaded = { data: [], error: null, loading: false };
    for (const role of ['TenantAdmin', 'TechnicalConsultant']) {
      roles = [role];
      const html = render();
      expect(html).toContain('No hay plan para 2027');
      expect(html).toContain('Crear plan 2027');
      expect(html).not.toContain('Solo el administrador de la explotación o un técnico pueden crear planes');
    }
  });

  it('tells a field worker why there is no create button', () => {
    loaded = { data: [], error: null, loading: false };
    roles = ['Farmer'];
    const html = render();
    expect(html).toContain('No hay plan para 2027');
    expect(html).not.toContain('Crear plan');
    expect(html).toContain('Solo el administrador de la explotación o un técnico pueden crear planes');
  });

  it('shows the campaign of the URL in the selector', () => {
    loaded = { data: [], error: null, loading: false };
    expect(render(2026)).toContain('2026');
  });

  it('says the session expired', () => {
    loaded = { data: null, error: new FastApiError(401, null), loading: false };
    expect(render()).toContain('Sesión caducada');
  });
});

describe('afterCreateConflict', () => {
  it('opens the open plan of the campaign, the newest version', () => {
    const list = [plan({ id: 'old', state: 'superseded', version: 1 }), plan({ id: 'cur', version: 2 }), plan({ id: 'other', campaign: 2026 })];
    expect(afterCreateConflict(list, 2027)).toBe('cur');
  });
  it('is null when there is nothing open', () => {
    expect(afterCreateConflict([plan({ state: 'superseded' })], 2027)).toBeNull();
  });
});

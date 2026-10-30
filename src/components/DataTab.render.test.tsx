import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

vi.mock('@nekazari/sdk', async () => {
  const { esT } = await import('../test/esT');
  return { useTranslation: () => ({ t: esT, i18n: { language: 'es' } }), i18n: {} };
});
vi.mock('../hooks/useLoad', () => ({ useLoad: () => ({ data: 'Trigo blando', error: null, loading: false, retry: vi.fn() }) }));

import type { PlanSheet } from '../api/types';
import { clone, COMPLETE, INCOMPLETE, makePlan, makeSheet, PARCELS, URN } from '../test/builders';
import { DataTab } from './DataTab';

const FARMER = { canWrite: true, technician: false };
const TECH = { canWrite: true, technician: true };
const noop = () => undefined;

const render = (sheet: PlanSheet, editable = true, roles = FARMER) =>
  renderToStaticMarkup(<DataTab plan={makePlan({ sheets: [sheet] })} sheet={sheet} parcels={PARCELS.parcels}
    editable={editable} roles={roles} onSaved={noop} onReload={noop} />);

describe('DataTab (es)', () => {
  it('lists what is missing, who provides it and the link to the owner', () => {
    const html = render(makeSheet({ result: clone(INCOMPLETE) }));
    expect(html).toContain('Faltan 5 datos para completar el cálculo');
    expect(html).toContain('Análisis de suelo (textura, pH, P, K)');
    expect(html).toContain('href="/module/soil?parcel=p1"');
  });

  it('a missing value is a dash with the missing chip, a measured one carries its chip', () => {
    const html = render(makeSheet({ result: clone(INCOMPLETE) }));
    expect(html).toContain('✕ falta');
    expect(html).toContain('>—<');
    const ok = render(makeSheet());
    expect(ok).toContain('● medido');
    expect(ok).toContain('Trigo blando');
  });

  it('translates the notices of the calculation', () => {
    const html = render(makeSheet());
    expect(html).toContain('Sin N mínimo del producto para TRZAX: se usa el N típico.');
  });

  it('a parcel without an identifier asks for one', () => {
    expect(render(makeSheet())).toContain('Escribir SIGPAC');
  });

  it('read only draws no input and no save button', () => {
    const html = render(makeSheet(), false);
    expect(html).not.toContain('<input');
    expect(html).not.toContain('<textarea');
    expect(html).not.toContain('Guardar cambios');
    expect(html).not.toContain('>Ajustar<');
  });

  it('the farmer can adjust only the availability of organic inputs', () => {
    const result = clone(COMPLETE);
    result.inputs['organic.0.availability'] = { value: 0.35, provenance: 'table:mapa2010', source: 'engine', note: null };
    const sheet = makeSheet({
      result,
      inputs: { ...makeSheet().inputs, organic: [{ material: 'Estiércol', rate_t_ha: 20, n_pct: 0.6, p2o5_pct: 0.3, k2o_pct: 0.5 }] },
    });
    const farmer = render(sheet);
    expect(farmer.split('>Ajustar<').length - 1).toBe(1);
    const tech = render(sheet, true, TECH);
    expect(tech.split('>Ajustar<').length - 1).toBeGreaterThan(1);
  });

  it('shows the technician adjustment as an adjusted value with its chip', () => {
    const result = clone(COMPLETE);
    result.inputs['soil.ph'] = { value: 7.2, provenance: 'entered', source: 'user:u1@2026-10-01', note: 'lab repeat' };
    expect(render(makeSheet({ result }))).toContain('⚑ ajustado');
  });

  it('shows the stored SIGPAC of a parcel', () => {
    const sheet = makeSheet({ parcels: [{ urn: URN, sigpac: '31:201:0:0:12:45:1' }] });
    expect(render(sheet, false)).toContain('31:201:0:0:12:45:1');
  });
});

import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

vi.mock('@nekazari/sdk', async () => {
  const { esT } = await import('../test/esT');
  return { useTranslation: () => ({ t: esT, i18n: { language: 'es' } }), i18n: {} };
});

import type { ZoneDosesResponse, ZoningInfo } from '../api/types';
import { makeSheet } from '../test/builders';
import { esT } from '../test/esT';
import { zoningLabel } from '../model/zoneDoses';

let zonings: { data: ZoningInfo[] | null; error: unknown; loading: boolean } = { data: [], error: null, loading: false };
const loads: unknown[][] = [];
vi.mock('../hooks/useLoad', () => ({
  useLoad: (_load: unknown, deps: unknown[], enabled = true) => {
    loads.push([deps, enabled]);
    return { ...zonings, retry: vi.fn() };
  },
}));

import { PrescriptionButton, ZoneDosesBlock, ZoneDosesResult } from './ZoneDosesBlock';

const NDVI: ZoningInfo = { run_id: 'run-1', method: 'vegetationIndex', variable: 'NDVI', date: '2026-10-14', zone_count: 4, has_vegetation_value: true };
const MANUAL: ZoningInfo = { run_id: 'run-2', method: 'manual', variable: null, date: '2026-09-01', zone_count: 3, has_vegetation_value: false };
const MULTI: ZoningInfo = { run_id: 'run-3', method: 'vegetationIndexMultiDate', variable: 'NDVI', date: '2026-10-14', image_date: '2026-05-20', zone_count: 4, has_vegetation_value: true };
const block = (sheet = makeSheet()) => renderToStaticMarkup(<ZoneDosesBlock planId="plan-1" sheet={sheet} parcels={[]} />);

const RES: ZoneDosesResponse = {
  plan: { id: 'plan-1', state: 'calculated', campaign: 2027 },
  sheet: { key: 'wheat', n_kg_ha: { min: 90, avg: 120, max: 150 }, crop: { eppo: 'TRZAX', n_fixing: false } },
  zoning: { run_id: 'run-1', method: 'vegetationIndex', variable: 'NDVI', date: '2026-10-14', zone_count: 3 },
  strategy: 'potential', strategy_unavailable: null,
  target: { n_kg_ha: 60, source: 'given', product: { name: 'Nitrate 27', n_pct: 27 } },
  cap: { pct: 20, min_n_kg_ha: 48, max_n_kg_ha: 72 },
  zones: [
    { zone_id: 'z1', label: 'Alta', rank: 1, area_ha: 2.5, basis: 'vigor', relative_vigor: 1.3, factor: 1.2, capped: true, n_kg_ha: 72, product_kg_ha: 266.67, soil_analysis: null, missing: [] },
    { zone_id: 'z2', label: null, rank: 2, area_ha: 2.5, basis: 'vigor', relative_vigor: 0.8, factor: 0.8, capped: false, n_kg_ha: 48, product_kg_ha: 177.78, soil_analysis: null, missing: [] },
    { zone_id: 'z3', label: 'Sin dato', rank: 3, area_ha: 2.5, basis: 'sheet', relative_vigor: null, factor: null, capped: false, n_kg_ha: 60, product_kg_ha: 222.22, soil_analysis: null, missing: ['mean_value'] },
  ],
  rest: { area_ha: 2.5, n_kg_ha: 60, product_kg_ha: 222.22 },
  totals: { area_ha: 10, n_kg: 600, mean_n_kg_ha: 60, uniform_n_kg: 600 },
  notices: [{ code: 'zoning_image_old', params: { date: '2026-09-01', days: 40 } }, { code: 'zones_do_not_cover_parcel', params: { rest_ha: 2.5, parcel_ha: 10 } }],
  units: { n: 'kg N/ha', product: 'kg/ha' }, versions: {},
};

describe('ZoneDosesBlock (es)', () => {
  it('says the figures are experimental and do not replace the technician', () => {
    zonings = { data: [NDVI], error: null, loading: false };
    const html = block();
    expect(html).toContain('Experimental');
    expect(html).toContain('no sustituyen el criterio del técnico');
  });

  it('with no zoning says so, names the modules and offers no form, no button', () => {
    zonings = { data: [], error: null, loading: false };
    const html = block();
    expect(html).toContain('no tiene ninguna zonificación guardada');
    expect(html).toContain('vegetación o de rutas');
    expect(html).not.toContain('Calcular reparto');
  });

  it('with zonings shows the form: strategy hint, cap, dose with the sheet need as reference only', () => {
    zonings = { data: [NDVI, MANUAL], error: null, loading: false };
    const html = block();
    expect(html).toContain('Dosis de N de esta pasada (kg N/ha)');
    expect(html).toContain('La misma dosis en todas las zonas.');
    expect(html).toContain('Tope de variación');
    expect(html).toContain('Calcular reparto');
    expect(html).toContain('Referencia: la necesidad de N de la hoja es');
    // the dose input starts empty: the sheet's need is never put in it
    expect(html).toMatch(/<input[^>]*type="number"[^>]*value=""/);
    // no dose typed yet: the button is disabled
    expect(html).toMatch(/<button[^>]*disabled[^>]*>[^<]*Calcular reparto/);
    expect(html).not.toContain('Llevar a receta');
  });

  it('shows no parcel selector for one parcel, and asks for the first parcel zonings', () => {
    zonings = { data: [NDVI], error: null, loading: false };
    loads.length = 0;
    expect(block()).not.toContain('Parcela');
    expect(loads[0]).toEqual([['plan-1', 'trzax-rainfed', 'urn:ngsi-ld:AgriParcel:p1'], true]);
  });

  it('shows a parcel selector when the sheet has several parcels', () => {
    zonings = { data: [NDVI], error: null, loading: false };
    const sheet = makeSheet({ parcels: [{ urn: 'urn:ngsi-ld:AgriParcel:p1', sigpac: null }, { urn: 'urn:ngsi-ld:AgriParcel:p2', sigpac: null }] });
    expect(block(sheet)).toContain('Parcela');
  });

  it('a failure to list the zonings is shown, not hidden as "no zoning"', () => {
    zonings = { data: null, error: new Error('x'), loading: false };
    const html = block();
    expect(html).toContain('role="alert"');
    expect(html).not.toContain('no tiene ninguna zonificación');
  });
});

describe('multi-date zonings (es)', () => {
  it('lists the zoning with its image date and shows zones by level, never the raw code', () => {
    const l = zoningLabel(MULTI, 'es');   // the closed select renders no option text
    expect(esT(l.key, l.params)).toBe('Satélite multifecha (NDVI) · imagen 20/05/2026 · 4 zonas');
    const zones = ['high', 'medium', 'low', 'critical', 'bogus'].map((level, i) => ({ ...RES.zones[0], zone_id: `m${i}`, label: level, rank: i + 1, level }));
    const html = renderToStaticMarkup(<ZoneDosesResult res={{ ...RES, zones }} />);
    for (const t of ['Vigor alto', 'Vigor medio', 'Vigor bajo', 'Vigor crítico', 'Zona 5']) expect(html).toContain(t);
    expect(html).not.toMatch(/>(high|medium|low|critical|bogus)</);
  });
});

describe('ZoneDosesResult (es)', () => {
  const html = renderToStaticMarkup(<ZoneDosesResult res={RES} />);

  it('lists every zone with area, relative vigor, kg N/ha and kg product/ha', () => {
    expect(html).toContain('Alta');
    expect(html).toContain('Zona 2');
    expect(html).toContain('1,30');
    expect(html).toContain('72,0');
    expect(html).toContain('48,0');
    expect(html).toContain('267');
  });

  it('writes the origin of each figure in words', () => {
    expect(html.match(/Ajuste por vigor de satélite/g)).toHaveLength(2);
    expect(html.match(/Dosis de parcela/g)).toHaveLength(2);   // the zone without data and the rest row
    expect(html).toContain('sin valor de vigor');
  });

  it('marks only the capped zone', () => {
    expect(html.match(/>Tope</g)).toHaveLength(1);
  });

  it('shows the rest row only when it has area, and the totals against the uniform one', () => {
    expect(html).toContain('Resto de la parcela');
    const none = renderToStaticMarkup(<ZoneDosesResult res={{ ...RES, rest: { area_ha: 0, n_kg_ha: 60, product_kg_ha: 222.22 } }} />);
    expect(none).not.toContain('Resto de la parcela');
    expect(html).toContain('Total 600 kg N · media 60,0 kg N/ha · con dosis uniforme 600 kg N');
  });

  it('translates every notice with its params', () => {
    expect(html).toContain('La imagen de la zonificación es del 01/09/2026 (40 días).');
    expect(html).toContain('quedan 2,5 ha de 10,0 ha');
  });

  it('with the strategy unavailable says why and that the uniform dose is shown', () => {
    const out = renderToStaticMarkup(<ZoneDosesResult res={{ ...RES, strategy_unavailable: 'zoning_without_vegetation_value', zones: RES.zones.map((z) => ({ ...z, basis: 'sheet' as const })) }} />);
    expect(out).toContain('No se puede aplicar el reparto «Potencial»');
    expect(out).toContain('las manuales no lo traen');
    expect(out).toContain('Se muestra la dosis uniforme.');
  });

  it('a missing figure is a dash, never 0', () => {
    const out = renderToStaticMarkup(<ZoneDosesResult res={{ ...RES, strategy_unavailable: 'no_target_n', zones: [{ ...RES.zones[1], n_kg_ha: null, product_kg_ha: null }], rest: { area_ha: 0, n_kg_ha: null, product_kg_ha: null }, totals: { area_ha: 2.5, n_kg: null, mean_n_kg_ha: null, uniform_n_kg: null }, notices: [] }} />);
    expect(out).toContain('Total — kg N · media — kg N/ha');
  });
});

describe('ZoneDosesResult zone soil (es)', () => {
  const sa = { id: 'zp0', date: '2026-09-15', n_samples: 2, p_date: '2026-09-15', k_date: '2026-09-15' };
  const soilRes: ZoneDosesResponse = {
    ...RES,
    zones: [
      { ...RES.zones[0], basis: 'zone_soil', outside_cap: true, capped: false, nmin_kg_ha: 29.7, p2o5_kg_ha: 71.2, k2o_kg_ha: 95, soil_analysis: sa },
      { ...RES.zones[1], p2o5_kg_ha: 50.3, k2o_kg_ha: 83.76 },
    ],
    rest: { ...RES.rest, p2o5_kg_ha: 50.3, k2o_kg_ha: 83.76 },
    notices: [
      { code: 'zone_soil_missing', params: { zones: ['Zona 2', 'Zona 3'] } },
      { code: 'zone_nmin_first_pass_only', params: { applied: true } },
      { code: 'zone_nmin_first_pass_only', params: { applied: false } },
      { code: 'zone_soil_unavailable', params: {} },
      { code: 'zone_dose_floored', params: { zone: 'Zona 1' } },
    ],
  };
  const html = renderToStaticMarkup(<ZoneDosesResult res={soilRes} />);
  it('has the P2O5 and K2O columns with the zone and rest values', () => {
    expect(html).toContain('kg P₂O₅/ha');
    expect(html).toContain('kg K₂O/ha');
    expect(html).toContain('71');
    expect(html).toContain('84');
    expect(html.match(/>50</g)).toHaveLength(2);
  });
  it('marks the zone analysis with date and samples, the others with the parcel mean', () => {
    expect(html).toContain('Análisis de la zona (15/09/2026, 2 muestras)');
    expect(html).toContain('Media de la parcela');
  });
  it('outside the cap has its own label, never the cap one', () => {
    expect(html).toContain('fuera de los límites por su Nmin');
    expect(html.match(/>Tope</g)).toBeNull();
  });
  it('translates the new notices', () => {
    expect(html).not.toContain('zoneDoses.notice');
    expect(html).not.toContain('>zone_');
    expect(html).toContain('Zona 2, Zona 3');
  });
  it('without zone samples the rows carry no mark and show the two columns', () => {
    const plain = renderToStaticMarkup(<ZoneDosesResult res={RES} />);
    expect(plain).not.toContain('Media de la parcela');
    expect(plain).not.toContain('Análisis de la zona');
    expect(plain).toContain('kg P₂O₅/ha');
  });
});

describe('PrescriptionButton (es)', () => {
  const U = 'urn:ngsi-ld:AgriParcel:parcel-1';
  it('is enabled with the hint when the answer is current and has product rates', () => {
    const out = renderToStaticMarkup(<PrescriptionButton res={RES} parcelUrn={U} current />);
    expect(out).toMatch(/<button[^>]*>[^<]*Llevar a receta/);
    expect(out).not.toMatch(/<button[^>]*disabled=""[^>]*>[^<]*Llevar a receta/);
    expect(out).toContain('elige la máquina y el patrón y genera la pasada');
  });
  it('is disabled and says why: no product, a missing rate, stale, too many zones', () => {
    const dis = (res: ZoneDosesResponse, current = true) => renderToStaticMarkup(<PrescriptionButton res={res} parcelUrn={U} current={current} />);
    const noProd = dis({ ...RES, target: { ...RES.target, product: null }, zones: RES.zones.map((z) => ({ ...z, product_kg_ha: null })), rest: { ...RES.rest, product_kg_ha: null } });
    expect(noProd).toMatch(/<button[^>]*disabled=""[^>]*>[^<]*Llevar a receta/);
    expect(noProd).toContain('Indica un producto');
    expect(dis({ ...RES, rest: { ...RES.rest, product_kg_ha: null } })).toContain('no tiene dosis de producto');
    expect(dis(RES, false)).toContain('han cambiado');
    expect(dis({ ...RES, zones: Array.from({ length: 51 }, (_, i) => ({ ...RES.zones[0], zone_id: `z${i}` })) })).toContain('como mucho 50 zonas');
  });
});

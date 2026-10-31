import { describe, expect, it } from 'vitest';
import type { OxideResult, SheetResult } from '../api/types';
import completeFx from '../test/fixtures/sheet-result-complete.json';
import { bandScale, N_TERMS, nBreakdown, oxideView } from './needs';

const R = completeFx as unknown as SheetResult;

describe('N terms', () => {
  it('every fixed input key exists in the result of the engine', () => {
    const missing = N_TERMS.flatMap(({ term, inputs }) => (typeof inputs === 'function' ? [] : inputs.filter((k) => !(k in R.inputs)).map((k) => `${term}:${k}`)));
    expect(missing).toEqual([]);
  });

  it('the rows add up to the engine figures (this lives in the test only: the UI never recalculates)', () => {
    const rows = nBreakdown(R);
    const n = R.n!;
    const terms = rows.filter((r) => r.kind === 'term').reduce((a, r) => a + r.value, 0);
    const divisor = rows.find((r) => r.kind === 'divisor')!.value;
    expect(Math.max(terms / divisor, 0)).toBeCloseTo(n.before_credits.avg_kg_ha, 6);
    const credits = rows.filter((r) => r.kind === 'credit').reduce((a, r) => a + r.value, 0);
    expect(n.before_credits.avg_kg_ha - credits).toBeCloseTo(n.avg_kg_ha, 6);
  });

  it('n_end carries its fixed citation and no chips', () => {
    const row = nBreakdown(R).find((r) => r.term === 'n_end')!;
    expect(row.citation).toBe('Villalobos 2020, tabla 4');
    expect(row.chips).toEqual([]);
  });

  it('an incomplete result has no breakdown', () => {
    expect(nBreakdown({ ...R, n: null })).toEqual([]);
  });

  it('the organic term collects the availability inputs present', () => {
    const withOrganic = { ...R, inputs: { ...R.inputs, 'organic.0.availability': { value: 0.3, provenance: 'table:x', source: 's', note: null } } } as SheetResult;
    expect(nBreakdown(withOrganic).find((r) => r.term === 'organic_available_n')!.chips).toHaveLength(1);
  });
});

describe('bandScale', () => {
  it('rounds the largest figure up to 50', () => {
    const { max, pct } = bandScale(R.n!);
    expect(max % 50).toBe(0);
    expect(max).toBeGreaterThanOrEqual(R.n!.max_kg_ha);
    expect(pct(max / 2)).toBe(50);
  });
});

describe('oxideView', () => {
  const base = R.p2o5 as OxideResult;
  it('the class is the API one, not a comparison with the threshold', () => {
    const v = oxideView({ ...base, soil_class: 'low', threshold_mg_kg: 999 });
    expect(v.soilClassKey).toBe('soilClass.low');
    expect(v.thresholdText).toBe('999');
  });
  it('strategy 4 has no class and no threshold', () => {
    const v = oxideView({ ...base, soil_class: null, threshold_mg_kg: null, high_from_mg_kg: null, basis: 'export', strategy: 4 });
    expect(v).toMatchObject({ soilClassKey: null, thresholdText: null, highFromText: null, basisKey: 'basis.export' });
  });
});

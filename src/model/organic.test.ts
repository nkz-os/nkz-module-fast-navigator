/// <reference types="vite/client" />
import { describe, expect, it } from 'vitest';
import backendSrc from '../../backend/app/inputs/organic.py?raw';
import { isOrganicMaterial, ORGANIC_MATERIALS } from './organic';

describe('organic materials', () => {
  it('are exactly the five the backend validates', () => {
    const line = /\nMATERIALS\s*=\s*\(([^)]*)\)/.exec(backendSrc);
    const backend = [...(line?.[1] ?? '').matchAll(/"([a-z_]+)"/g)].map((m) => m[1]).sort();
    expect([...ORGANIC_MATERIALS].sort()).toEqual(backend);
  });
  it('recognises only those', () => {
    expect(isOrganicMaterial('slurry')).toBe(true);
    expect(isOrganicMaterial('estiércol')).toBe(false);
    expect(isOrganicMaterial('')).toBe(false);
  });
});

import { applyProduct, editComposition, productName, type OrganicProduct } from './organic';

const nut = (value: number, min = value, max = value) => ({ value, min, max });
const COW: OrganicProduct = {
  id: 'cattle_manure_table', material: 'cattle_manure', basis: 'fresh', source_ref: 'MAPA 2010, ch. 6, p. 47, table 6.7',
  n_pct: nut(0.45, 0.3, 0.6), p2o5_pct: nut(0.25, 0.1, 0.4), k2o_pct: nut(0.7, 0.4, 1),
  names: { es: 'Estiércol de vacuno', en: 'Cattle manure' },
};
const BLANK = { material: '', rate_t_ha: 12, n_pct: 0, p2o5_pct: 0, k2o_pct: 0 };

describe('organic product suggestions', () => {
  it('one pick fills type and the three % at once, keeps the rate, and marks the source', () => {
    expect(applyProduct(BLANK, COW)).toEqual({
      material: 'cattle_manure', rate_t_ha: 12, n_pct: 0.45, p2o5_pct: 0.25, k2o_pct: 0.7,
      composition_source: 'table:mapa_guia_2010',
    });
  });
  it('editing a %, or the material, turns the source into declared', () => {
    const picked = applyProduct(BLANK, COW);
    expect(editComposition(picked, { n_pct: 0.5 }).composition_source).toBe('declared');
    expect(editComposition(picked, { material: 'slurry' }).composition_source).toBe('declared');
    expect(editComposition(picked, { n_pct: 0.5 }).n_pct).toBe(0.5);
  });
  it('the name follows the language, falling back to English then Spanish', () => {
    expect(productName(COW, 'es-ES')).toBe('Estiércol de vacuno');
    expect(productName(COW, 'pt')).toBe('Cattle manure');
  });
});

/// <reference types="vite/client" />
import { describe, expect, it } from 'vitest';
import es from './locales/es.json';
import en from './locales/en.json';
import ca from './locales/ca.json';
import eu from './locales/eu.json';
import fr from './locales/fr.json';
import pt from './locales/pt.json';
import { ORGANIC_MATERIALS } from './model/organic';
import { PARAMS, paramLabelKey } from './model/params';

const SOURCES = import.meta.glob('./**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const FILES = Object.keys(SOURCES).filter((f) => !/\.test\.tsx?$/.test(f));
const BACKEND = import.meta.glob('/backend/app/**/*.py', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;

const LOCALES: [string, unknown][] = [['es', es], ['en', en], ['eu', eu], ['fr', fr], ['ca', ca], ['pt', pt]];

const lookup = (dict: unknown, key: string): unknown =>
  key.split('.').reduce<unknown>((n, p) => (n && typeof n === 'object' ? (n as Record<string, unknown>)[p] : undefined), dict);
const has = (dict: unknown, key: string) => ['', '_one', '_other'].some((s) => typeof lookup(dict, key + s) === 'string');

/** Every literal t('a.b') of the sources, which must exist in every language. */
function literalKeys(): string[] {
  const re = /\bt\(\s*(['"])([A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+)\1/g;
  return [...new Set(FILES.flatMap((f) => [...SOURCES[f].matchAll(re)].map((m) => m[2])))];
}

/** Notice codes of the backend: `Notice("code"` plus the ones chosen by a condition. */
function noticeCodes(): string[] {
  const found = Object.values(BACKEND).flatMap((src) => [...src.matchAll(/Notice\(\s*"([a-z0-9_]+)"/g)].map((m) => m[1]));
  const chosen = ['soil_p_method_unknown', 'soil_k_method_unknown', 'nmin_no_values', 'nmin_bulk_density_unknown'];
  return [...new Set([...found, ...chosen])];
}

const FAMILIES = [
  ...noticeCodes().map((c) => `notice.${c}`),
  ...['crop', 'previous_crop', 'yield', 'previous_yield', 'soil', 'irrigation', 'parcel', 'organic', 'region'].map((g) => `missing.${g}`),
  ...['plan', 'soil', 'bioorch', 'broker'].map((o) => `owner.${o}`),
  ...['bioorch', 'soil', 'weather_api', 'broker', 'broker_crop_cycles'].map((s) => `source.${s}`),
  ...['draft', 'calculated', 'in_review', 'signed', 'superseded'].map((s) => `state.${s}`),
  ...['measured', 'table', 'declared', 'entered', 'estimated', 'missing', 'plannedBioorch', 'sown', 'unknown'].map((p) => `provenance.${p}`),
  ...['measured', 'table', 'declared', 'entered', 'estimated', 'missing', 'planned'].map((p) => `provenance.tip.${p}`),
  ...['low', 'medium', 'high'].map((c) => `soilClass.${c}`),
  ...['buildup', 'buildup_and_export', 'export', 'half_export', 'none'].map((b) => `basis.${b}`),
  ...['session', 'forbidden', 'planNotFound', 'parcelNotFound', 'conflict', 'gatewayTimeout', 'sourceUnavailable', 'invalid', 'generic', 'planStays', 'rules'].map((k) => `error.${k}`),
  ...['stale_calculation', 'blocking_findings', 'advice_required', 'not_allowed'].map((c) => `error.transition.${c}`),
  // Keys the wizard picks at run time.
  ...[1, 2, 3].map((n) => `wizard.step${n}`),
  ...['rainfed', 'irrigated', 'unknown'].map((r) => `wizard.regime.${r}`),
  ...[1, 2, 3, 4].map((n) => `wizard.strategy.${n}`),
  ...['regime', 'tillage', 'rotation', 'crop', 'tooManySheets', 'tooManyParcels', 'nothing'].map((b) => `wizard.blocker.${b}`),
  ...Object.keys(PARAMS).map(paramLabelKey),
  ...['soil', 'bioorch', 'plan', 'broker', 'unknown'].map((o) => `ownerLink.${o}`),
  ...['zone', 'declared', 'entered', 'history', 'missing'].map((b) => `data.basis.${b}`),
  ...['crop_uptake', 'n_end', 'previous_residues', 'previous_roots', 'n_other', 'fixation', 'loss_divisor', 'soil_mineral_n', 'organic_available_n'].map((k) => `needs.term.${k}`),
  ...ORGANIC_MATERIALS.map((m) => `data.organic.materials.${m}`),
  'data.missing.title', 'workspace.signedByAdvisor', 'workspace.signedByHolder', 'param.soil_texture_class',
];

describe('strings', () => {
  it.each(LOCALES)('%s has every key the UI uses', (_lang, dict) => {
    const missing = [...literalKeys(), ...FAMILIES].filter((k) => !has(dict, k));
    expect(missing).toEqual([]);
  });

  it('the backend notice codes were found', () => {
    expect(noticeCodes().length).toBeGreaterThan(25);
  });

  it.each(LOCALES.filter(([l]) => l !== 'es'))('%s has no key that es lacks, and no marker left', (_lang, dict) => {
    const flat = (node: unknown, prefix = ''): string[] => (node && typeof node === 'object'
      ? Object.entries(node as Record<string, unknown>).flatMap(([k, v]) => flat(v, prefix ? `${prefix}.${k}` : k))
      : [prefix]);
    const esKeys = new Set(flat(es));
    expect(flat(dict).filter((k) => !esKeys.has(k))).toEqual([]);
    expect(flat(es).filter((k) => !has(dict, k))).toEqual([]);
  });
});

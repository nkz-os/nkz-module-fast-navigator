import type { NResult, OxideResult, SheetResult, Sourced } from '../api/types';

export type NTermName = 'crop_uptake' | 'n_end' | 'previous_residues' | 'previous_roots' | 'n_other' | 'fixation'
  | 'loss_divisor' | 'soil_mineral_n' | 'organic_available_n';

/** Which inputs of the result source each term of the N balance (so each row gets its chips). */
export const N_TERMS: { term: NTermName; inputs: string[] | ((r: SheetResult) => string[]) }[] = [
  { term: 'crop_uptake', inputs: ['yield.kg_ha', 'crop.n_product_pct', 'crop.n_residue_pct', 'crop.harvest_index_pct', 'crop.dm_product_pct'] },
  { term: 'n_end', inputs: [] },
  { term: 'previous_residues', inputs: ['previous_crop.eppo', 'previous_yield.kg_ha', 'previous_crop.n_residue_pct', 'previous_crop.residue_left_pct'] },
  { term: 'previous_roots', inputs: ['previous_crop.eppo', 'previous_yield.kg_ha', 'previous_crop.n_product_pct', 'previous_crop.harvest_index_pct'] },
  { term: 'n_other', inputs: ['irrigation.n_kg_ha'] },
  { term: 'fixation', inputs: ['crop.n_fixing'] },
  { term: 'loss_divisor', inputs: ['management.tillage', 'management.irrigated'] },
  { term: 'soil_mineral_n', inputs: ['soil.mineral_n_kg_ha'] },
  { term: 'organic_available_n', inputs: (r) => Object.keys(r.inputs).filter((k) => /^organic\.\d+\.availability$/.test(k)) },
];

/** The fixed citation of the term that comes from a table of the method, not from an input. */
export const N_END_CITATION = 'Villalobos 2020, tabla 4';

export interface BreakdownRow {
  term: NTermName;
  value: number;
  kind: 'term' | 'divisor' | 'credit';
  chips: Sourced[];
  citation?: string;
}

/**
 * The rows of the N balance as the engine reports them for the mean level: signed terms, the loss
 * divisor, then the credits taken off. Nothing is computed here: values are the API's.
 */
export function nBreakdown(r: SheetResult): BreakdownRow[] {
  const n = r.n;
  if (!n) return [];
  const chipsOf = (keys: string[]): Sourced[] => keys.map((k) => r.inputs[k]).filter((s): s is Sourced => !!s && 'provenance' in s);
  const value = (term: NTermName): number => {
    if (term === 'soil_mineral_n') return n.credits_kg_ha.soil_mineral_n;
    if (term === 'organic_available_n') return n.credits_kg_ha.organic_available_n;
    return n.terms_kg_ha[term];
  };
  return N_TERMS.map(({ term, inputs }) => {
    const keys = typeof inputs === 'function' ? inputs(r) : inputs;
    const kind: BreakdownRow['kind'] = term === 'loss_divisor' ? 'divisor' : term === 'soil_mineral_n' || term === 'organic_available_n' ? 'credit' : 'term';
    return { term, value: value(term), kind, chips: chipsOf(keys), ...(term === 'n_end' ? { citation: N_END_CITATION } : {}) };
  });
}

/** Drawing scale of the N band: the largest figure rounded up to 50. */
export function bandScale(n: NResult): { max: number; pct: (v: number) => number } {
  const top = Math.max(...n.levels_kg_ha, n.before_credits.max_kg_ha, n.max_kg_ha);
  const max = Math.max(50, Math.ceil(top / 50) * 50);
  return { max, pct: (v) => Math.min(100, Math.max(0, (v / max) * 100)) };
}

export interface OxideView {
  soilClassKey: string | null;
  basisKey: string;
  thresholdText: string | null;
  highFromText: string | null;
}

/** How to read P2O5 / K2O: the class and the basis come from the engine; nothing is compared here. */
export function oxideView(o: OxideResult): OxideView {
  return {
    soilClassKey: o.soil_class ? `soilClass.${o.soil_class}` : null,
    basisKey: `basis.${o.basis}`,
    thresholdText: o.threshold_mg_kg == null ? null : String(Math.round(o.threshold_mg_kg)),
    highFromText: o.high_from_mg_kg == null ? null : String(Math.round(o.high_from_mg_kg)),
  };
}

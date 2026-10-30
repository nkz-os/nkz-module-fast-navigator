/** Parameters of a sheet shown in the Data tab: unit and decimals; the label is `param.<dots as underscores>`. */
export interface ParamInfo { unit: string | null; digits: number }

export const SOIL_PARAMS = ['soil.sand_pct', 'soil.clay_pct', 'soil.ph', 'soil.organic_matter_pct', 'soil.p_olsen_mg_kg',
  'soil.k_mg_kg', 'soil.bulk_density_g_cm3', 'soil.mineral_n_kg_ha'] as const;
export const YIELD_PARAMS = ['yield.kg_ha', 'yield.cv_pct'] as const;
export const WATER_PARAMS = ['irrigation.water_m3_ha', 'irrigation.no3_mg_l', 'irrigation.uptake', 'irrigation.n_kg_ha'] as const;
export const COEFFICIENT_PARAMS = ['crop.dm_product_pct', 'crop.harvest_index_pct', 'crop.residue_left_pct', 'crop.n_product_pct',
  'crop.n_min_product_pct', 'crop.p_product_pct', 'crop.k_product_pct', 'crop.n_residue_pct', 'crop.p_residue_pct', 'crop.k_residue_pct'] as const;

export const PARAMS: Record<string, ParamInfo> = {
  'soil.sand_pct': { unit: '%', digits: 1 }, 'soil.clay_pct': { unit: '%', digits: 1 }, 'soil.ph': { unit: null, digits: 1 },
  'soil.organic_matter_pct': { unit: '%', digits: 1 }, 'soil.p_olsen_mg_kg': { unit: 'mg/kg', digits: 0 },
  'soil.k_mg_kg': { unit: 'mg/kg', digits: 0 }, 'soil.bulk_density_g_cm3': { unit: 'g/cm³', digits: 2 },
  'soil.mineral_n_kg_ha': { unit: 'kg/ha', digits: 0 },
  'yield.kg_ha': { unit: 'kg/ha', digits: 0 }, 'yield.cv_pct': { unit: '%', digits: 1 },
  'irrigation.water_m3_ha': { unit: 'm³/ha', digits: 0 }, 'irrigation.no3_mg_l': { unit: 'mg/L', digits: 0 },
  'irrigation.uptake': { unit: null, digits: 2 }, 'irrigation.n_kg_ha': { unit: 'kg/ha', digits: 0 },
  ...Object.fromEntries(COEFFICIENT_PARAMS.map((p) => [p, { unit: '%', digits: 2 }])),
};

export const paramLabelKey = (param: string) => `param.${param.replace(/\./g, '_')}`;

export function formatParam(param: string, value: unknown, lang: string): string {
  const info = PARAMS[param];
  if (typeof value !== 'number') return String(value);
  return new Intl.NumberFormat(lang, { minimumFractionDigits: info?.digits ?? 0, maximumFractionDigits: info?.digits ?? 2 }).format(value);
}

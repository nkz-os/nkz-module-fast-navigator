import type { Roles } from './roles';

/** Ranges a person may type over a source's value (mirror of the backend table; the API has the last word). */
const CROP: Record<string, [number, number]> = {
  dm_product_pct: [0.01, 100], harvest_index_pct: [0.01, 100], residue_left_pct: [0, 100],
  n_product_pct: [0, 10], n_min_product_pct: [0, 10], p_product_pct: [0, 10], k_product_pct: [0, 10],
  n_residue_pct: [0, 10], p_residue_pct: [0, 10], k_residue_pct: [0, 10],
};
const YIELD: Record<string, [number, number]> = { kg_ha: [1, 200000], cv_pct: [0, 100] };
const SOIL: Record<string, [number, number]> = {
  sand_pct: [0, 100], clay_pct: [0, 100], ph: [0, 14], organic_matter_pct: [0, 100],
  p_olsen_mg_kg: [0, 500], k_mg_kg: [0, 3000], texture_class: [1, 6], bulk_density_g_cm3: [0.1, 2.65],
};

export const FARMER_PARAM = /^organic\.(0|[1-9][0-9]*)\.availability$/;

export function overrideRange(param: string): [number, number] | null {
  const [head, ...rest] = param.split('.');
  const tail = rest.join('.');
  if (head === 'crop' || head === 'previous_crop') return CROP[tail] ?? null;
  if (head === 'yield' || head === 'previous_yield') return YIELD[tail] ?? null;
  if (head === 'soil') return SOIL[tail] ?? null;
  if (param === 'irrigation.uptake' || FARMER_PARAM.test(param)) return [0, 1];
  return null;
}

/** Who sees "Adjust" on a value: the farmer only on the N availability of organic inputs. */
export function mayAdjust(param: string, roles: Roles): boolean {
  if (FARMER_PARAM.test(param)) return roles.canWrite;
  return roles.technician && overrideRange(param) !== null;
}

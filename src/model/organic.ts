/** The materials the backend accepts for an organic input (`app/inputs/organic.py`); anything else is a 422. */
export const ORGANIC_MATERIALS = ['cattle_manure', 'other_manure', 'slurry', 'compost', 'other'] as const;
export type OrganicMaterial = (typeof ORGANIC_MATERIALS)[number];

export const isOrganicMaterial = (v: string): v is OrganicMaterial => (ORGANIC_MATERIALS as readonly string[]).includes(v);

/** One figure of the MAPA guide: `value` is the midpoint when the guide prints a range. */
export interface OrganicNutrient { value: number; min: number; max: number }
export interface OrganicProduct {
  id: string;
  material: OrganicMaterial;
  n_pct: OrganicNutrient;
  p2o5_pct: OrganicNutrient;
  k2o_pct: OrganicNutrient;
  basis: 'fresh' | 'not_stated';
  source_ref: string;
  names: Record<string, string>;
}
export interface OrganicProducts { products: OrganicProduct[]; attribution: { source_id: string; text: string; url?: string | null } }

export type CompositionSource = 'table:mapa_guia_2010' | 'declared';
export interface OrganicLike {
  material: string; rate_t_ha: number; n_pct: number; p2o5_pct: number; k2o_pct: number;
  composition_source?: CompositionSource;
}

export const productName = (p: OrganicProduct, lang: string): string => {
  const { names } = p;
  return names[lang.split('-')[0]] ?? names['en'] ?? names['es'] ?? p.id;
};

/** Picking a product fills the type and the three contents at once; the rate stays the user's. */
export const applyProduct = (o: OrganicLike, p: OrganicProduct): OrganicLike => ({
  ...o, material: p.material, n_pct: p.n_pct.value, p2o5_pct: p.p2o5_pct.value, k2o_pct: p.k2o_pct.value,
  composition_source: 'table:mapa_guia_2010',
});

/** Editing the material or a content leaves the suggestion: from then on it is the user's figure. */
export const editComposition = (o: OrganicLike, patch: Partial<Pick<OrganicLike, 'material' | 'n_pct' | 'p2o5_pct' | 'k2o_pct'>>): OrganicLike =>
  ({ ...o, ...patch, composition_source: 'declared' });

/** The materials the backend accepts for an organic input (`app/inputs/organic.py`); anything else is a 422. */
export const ORGANIC_MATERIALS = ['cattle_manure', 'other_manure', 'slurry', 'compost', 'other'] as const;
export type OrganicMaterial = (typeof ORGANIC_MATERIALS)[number];

export const isOrganicMaterial = (v: string): v is OrganicMaterial => (ORGANIC_MATERIALS as readonly string[]).includes(v);

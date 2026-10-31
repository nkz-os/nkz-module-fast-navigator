/** Crops the user picks by name: the FaST list (`/sources/crops`), searched in the user's language. */

export interface SourceCrop {
  eppo: string;
  names: Record<string, string>;
  has_coefficients: boolean;
}

/** The value of a previous crop that is a fallow (the backend's own word). */
export const FALLOW = 'fallow';

export function cropDisplayName(crop: SourceCrop, lang: string): string {
  const base = lang.split('-')[0];
  const { names } = crop;
  return names[base] ?? names['en'] ?? names['es'] ?? crop.eppo;
}

const norm = (s: string) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim();

/** Crops whose name (in any language) or code contains `query`; the ones that start with it first. */
export function filterCrops(crops: SourceCrop[], query: string, lang: string, limit = 8): SourceCrop[] {
  const q = norm(query);
  if (q === '') return crops.slice(0, limit);
  const rank = (c: SourceCrop): number => {
    const own = norm(cropDisplayName(c, lang));
    const all = [...Object.values(c.names), c.eppo].map(norm);
    if (own.startsWith(q)) return 0;
    if (all.some((n) => n.startsWith(q))) return 1;
    if (all.some((n) => n.includes(q))) return 2;
    return 3;
  };
  return crops.map((c) => [rank(c), c] as const).filter(([r]) => r < 3)
    .sort((a, b) => a[0] - b[0]).map(([, c]) => c).slice(0, limit);
}

/** Whether FaST can calculate with the crop: listed with coefficients (a fallow needs none). */
export function hasCoefficients(crops: SourceCrop[], eppo: string): boolean {
  if (eppo === FALLOW) return true;
  return crops.find((c) => c.eppo === eppo)?.has_coefficients === true;
}

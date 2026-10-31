/** Declared yields (kg/ha, fresh) per previous year: the next year to offer and the validity of a new one. */

/** The most recent campaign before `campaign` that has no declared yield yet. */
export function nextDeclarableYear(campaign: number, declared: Record<string, number>): number {
  let y = campaign - 1;
  while (String(y) in declared) y -= 1;
  return y;
}

export type YearProblem = 'year' | 'future' | 'duplicate' | 'yield' | null;

/** Why a (year, yield) pair cannot be added, or null when it can. The backend accepts years 2000-2100 and yields > 0. */
export function yearProblem(campaign: number, declared: Record<string, number>, year: number, kg: number | null): YearProblem {
  if (!Number.isInteger(year) || year < 2000) return 'year';
  if (year >= campaign) return 'future';
  if (String(year) in declared) return 'duplicate';
  if (kg === null || !Number.isFinite(kg) || kg <= 0 || kg > 200_000) return 'yield';
  return null;
}

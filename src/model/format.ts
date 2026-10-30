/** Numbers and dates for the active language: kg/ha and mg/kg whole, % and ha with one decimal. */
const DASH = '—';

function fmt(v: number | null | undefined, lang: string, digits: number): string {
  if (v == null || !Number.isFinite(v)) return DASH;
  return new Intl.NumberFormat(lang, { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(v);
}

export const formatKgHa = (v: number | null | undefined, lang: string) => fmt(v, lang, 0);
export const formatMgKg = (v: number | null | undefined, lang: string) => fmt(v, lang, 0);
export const formatPct = (v: number | null | undefined, lang: string) => fmt(v, lang, 1);
export const formatHa = (v: number | null | undefined, lang: string) => fmt(v, lang, 1);

/** A date (`2026-10-14`) or a timestamp: numeric day-month-year in the language's order. */
export function formatDate(iso: string | null | undefined, lang: string): string {
  if (!iso) return DASH;
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(iso);
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat(lang, {
    day: '2-digit', month: '2-digit', year: 'numeric', ...(dateOnly ? { timeZone: 'UTC' } : {}),
  }).format(d);
}

/** The PDF exists in Spanish and English. */
export const pdfLang = (lang: string): 'es' | 'en' => (lang.toLowerCase().startsWith('en') ? 'en' : 'es');

export { DASH };

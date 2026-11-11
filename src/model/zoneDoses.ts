import type { ZoneBasis, ZoneDosesRequest, ZoneDosesResponse, ZoneDoseRow, ZoneStrategy, ZoningInfo } from '../api/types';
import { DASH, formatDate, formatHa } from './format';

/** Text typed by the technician to a number: a decimal comma is accepted; anything else is null. */
export function parseNumber(text: string): number | null {
  const s = text.trim().replace(',', '.');
  if (s === '') return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

export interface RequestInputs {
  parcelUrn: string | null;
  runId: string | null;
  strategy: ZoneStrategy;
  capText: string;
  targetText: string;
  productName: string;
  nPctText: string;
}
export type RequestProblem = 'noZoning' | 'target' | 'cap' | 'product';
export type BuiltRequest = { ok: true; body: ZoneDosesRequest } | { ok: false; problem: RequestProblem };

/** Limits of the API: the dose is above 0 up to 1000 kg N/ha, the cap 0-30 %, the richness above 0 up to 100 %. */
export function buildZoneDosesRequest(i: RequestInputs): BuiltRequest {
  if (!i.parcelUrn || !i.runId) return { ok: false, problem: 'noZoning' };
  const n = parseNumber(i.targetText);
  if (n === null || n <= 0 || n > 1000) return { ok: false, problem: 'target' };
  const cap = parseNumber(i.capText);
  if (cap === null || cap < 0 || cap > 30) return { ok: false, problem: 'cap' };
  const name = i.productName.trim();
  const richness = parseNumber(i.nPctText);
  const target: ZoneDosesRequest['target'] = { n_kg_ha: n };
  if (name !== '' || i.nPctText.trim() !== '') {
    if (name === '' || richness === null || richness <= 0 || richness > 100) return { ok: false, problem: 'product' };
    target.product = { name, n_pct: richness };
  }
  return { ok: true, body: { parcel_urn: i.parcelUrn, zoning_run_id: i.runId, strategy: i.strategy, cap_pct: cap, target } };
}

export interface LabelView { key: string; params: Record<string, string | number> }

/** A zoning by how it was made, when and how many zones: a manual one is said so. */
export function zoningLabel(z: ZoningInfo, lang: string): LabelView {
  const date = formatDate(z.date, lang);
  if (z.method === 'vegetationIndex') return { key: 'zoneDoses.zoning.vegetationIndex', params: { variable: z.variable ?? DASH, date, count: z.zone_count } };
  if (z.method === 'manual') return { key: 'zoneDoses.zoning.manual', params: { date, count: z.zone_count } };
  return { key: 'zoneDoses.zoning.other', params: { date, count: z.zone_count } };
}

/** The zone's own label, else "Zone n" from its rank (or its position). */
export function zoneLabel(z: Pick<ZoneDoseRow, 'label' | 'rank'>, index: number): { text: string } | { key: string; params: { n: number } } {
  if (z.label) return { text: z.label };
  return { key: 'zoneDoses.zoneN', params: { n: z.rank ?? index + 1 } };
}

export const basisKey = (b: ZoneBasis) => `zoneDoses.basis.${b}`;
export const unavailableKey = (reason: string) => `zoneDoses.unavailable.${reason}`;

const HA_PARAMS = new Set(['rest_ha', 'parcel_ha', 'zones_ha']);

/** A notice of the API as a key with its params written for the language. */
export function noticeView(n: ZoneDosesResponse['notices'][number], lang: string): { key: string; params: Record<string, string> } {
  const params: Record<string, string> = {};
  for (const [k, v] of Object.entries(n.params ?? {})) {
    if (v == null) params[k] = DASH;
    else if (k === 'date') params[k] = formatDate(String(v), lang);
    else if (HA_PARAMS.has(k) && typeof v === 'number') params[k] = formatHa(v, lang);
    else params[k] = String(v);
  }
  return { key: `zoneDoses.notice.${n.code}`, params };
}

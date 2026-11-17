import type { ZoneBasis, ZoneDosesRequest, ZoneDosesResponse, ZoneDoseRow, ZoneStrategy, ZoningInfo } from '../api/types';
import { DASH, formatDate, formatHa, formatKgHa } from './format';

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
  if (z.method === 'vegetationIndexMultiDate') return { key: 'zoneDoses.zoning.vegetationIndexMultiDate', params: { variable: z.variable ?? DASH, date: formatDate(z.image_date ?? z.date, lang), count: z.zone_count } };
  if (z.method === 'manual') return { key: 'zoneDoses.zoning.manual', params: { date, count: z.zone_count } };
  return { key: 'zoneDoses.zoning.other', params: { date, count: z.zone_count } };
}

export const ZONE_LEVELS = ['high', 'medium', 'low', 'critical'] as const;

/**
 * A zone with a vigor level is named in the user's language from the level (never from the stored
 * label); a level this screen does not know is not shown, it falls back to "Zone n". Without a level:
 * the zone's own label, else "Zone n" from its rank (or its position).
 */
export function zoneLabel(z: Pick<ZoneDoseRow, 'label' | 'rank' | 'level'>, index: number): { text: string } | { key: string; params: { n: number } } {
  const n = z.rank ?? index + 1;
  if (z.level != null) {
    return (ZONE_LEVELS as readonly string[]).includes(z.level) ? { key: `zoneDoses.level.${z.level}`, params: { n } } : { key: 'zoneDoses.zoneN', params: { n } };
  }
  if (z.label) return { text: z.label };
  return { key: 'zoneDoses.zoneN', params: { n: z.rank ?? index + 1 } };
}

export const basisKey = (b: ZoneBasis) => `zoneDoses.basis.${b}`;
export const unavailableKey = (reason: string) => `zoneDoses.unavailable.${reason}`;

const HA_PARAMS = new Set(['rest_ha', 'parcel_ha', 'zones_ha']);
const DATE_PARAMS = new Set(['date', 'p_date', 'k_date']);
const ZONE_NOTICES_WITH_APPLIED = new Set(['zone_nmin_first_pass_only']);

/**
 * A notice of the API as a key with its params written for the language. `zoneName` turns a zone
 * id (or stored label) of the notice into the name the table shows for it.
 */
export function noticeView(n: ZoneDosesResponse['notices'][number], lang: string, zoneName?: (idOrLabel: string) => string): { key: string; params: Record<string, string> } {
  const params: Record<string, string> = {};
  for (const [k, v] of Object.entries(n.params ?? {})) {
    if (v == null) params[k] = DASH;
    else if (DATE_PARAMS.has(k)) params[k] = formatDate(String(v), lang);
    else if (HA_PARAMS.has(k) && typeof v === 'number') params[k] = formatHa(v, lang);
    else if (Array.isArray(v)) params[k] = v.map((x) => (zoneName ? zoneName(String(x)) : String(x))).join(', ');
    else if (k === 'zone' && zoneName) params[k] = zoneName(String(v));
    else params[k] = String(v);
  }
  // A notice that reads differently by a flag has one text per value.
  const suffix = ZONE_NOTICES_WITH_APPLIED.has(n.code) ? (n.params?.applied === true ? '_applied' : '_not_applied') : '';
  return { key: `zoneDoses.notice.${n.code}${suffix}`, params };
}

/**
 * Where the zone's P, K and Nmin figures come from: its own analysis (with the date, or the two
 * dates when P and K differ, and the number of samples) or the parcel mean.
 */
export function zoneMark(z: Pick<ZoneDoseRow, 'basis' | 'soil_analysis' | 'nmin_kg_ha'>, lang: string): { key: string; params: Record<string, string | number>; nmin?: string } {
  const a = z.soil_analysis;
  if (z.basis !== 'zone_soil' || !a) return { key: 'zoneDoses.mark.parcel', params: {} };
  const count = a.n_samples && a.n_samples > 0 ? a.n_samples : null;
  const sfx = count == null ? 'NoCount' : '';
  const extra: Record<string, number> = count == null ? {} : { count };
  const nmin = z.nmin_kg_ha != null ? formatKgHa(z.nmin_kg_ha, lang) : undefined;
  const out = (key: string, params: Record<string, string | number>) => ({ key, params: { ...params, ...extra }, ...(nmin !== undefined ? { nmin } : {}) });
  if (a.p_date && a.k_date && a.p_date !== a.k_date) {
    return out(`zoneDoses.mark.zoneSoilPK${sfx}`, { p: formatDate(a.p_date, lang), k: formatDate(a.k_date, lang) });
  }
  return out(`zoneDoses.mark.zoneSoil${sfx}`, { date: formatDate(a.date ?? a.p_date ?? a.k_date, lang) });
}

/** The routing module reads at most this many zone rates from the link. */
export const MAX_PRESCRIPTION_ZONES = 50;
/** Route of the routing module, as it declares it in its module definition. */
export const ROUTING_ROUTE = '/gis-routing';

export type PrescriptionBlock = 'stale' | 'noProduct' | 'missingRate' | 'tooManyZones';
export type PrescriptionLink = { ok: true; path: string } | { ok: false; reason: PrescriptionBlock };

/** RFC 4648 section 5 alphabet, no padding, over the UTF-8 bytes of the text. */
export function base64UrlEncode(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let bin = '';
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

const isRate = (v: number | null | undefined): v is number => typeof v === 'number' && Number.isFinite(v) && v >= 0;

/**
 * The link that opens the routing module with the product rates of the CURRENT answer filled in.
 * Never partial: any missing rate, no product or too many zones gives a reason instead of a link.
 */
export function buildPrescriptionLink(i: { res: ZoneDosesResponse; parcelUrn: string; current: boolean }): PrescriptionLink {
  const { res } = i;
  if (!i.current) return { ok: false, reason: 'stale' };
  const product = res.target.product;
  if (!product) return { ok: false, reason: 'noProduct' };
  if (res.zones.length > MAX_PRESCRIPTION_ZONES) return { ok: false, reason: 'tooManyZones' };
  const rest = res.rest.product_kg_ha;
  const nDose = res.target.n_kg_ha;
  if (res.zones.length === 0 || !isRate(rest) || !isRate(nDose) || !res.zones.every((z) => isRate(z.product_kg_ha))) {
    return { ok: false, reason: 'missingRate' };
  }
  const zone_rates: Record<string, number> = {};
  for (const z of res.zones) zone_rates[z.zone_id] = z.product_kg_ha as number;
  const payload = {
    v: 1, source: 'fast', zoning_run_id: res.zoning.run_id, unit: 'kg_ha', product: product.name,
    zone_rates, rest_rate: rest,
    origin: { plan: res.plan.id, sheet: res.sheet.key, strategy: res.strategy_unavailable ? 'uniform' : res.strategy, n_kg_ha: nDose },
  };
  const vra = base64UrlEncode(JSON.stringify(payload));
  return { ok: true, path: `${ROUTING_ROUTE}?view=work&parcel=${encodeURIComponent(i.parcelUrn)}&vra=${vra}` };
}

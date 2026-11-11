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

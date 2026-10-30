import type { CampaignParcel, PlanSheet, PlanSheetIn, SheetResult, Sourced } from '../api/types';

/** A stored sheet back into the body of PUT /sheets: nothing is dropped (overrides are kept by key). */
export function toSheetIn(sheet: PlanSheet, campaign: number): PlanSheetIn {
  const sigpac: Record<string, string> = {};
  for (const p of sheet.parcels) if (p.sigpac) sigpac[p.urn] = p.sigpac;
  return {
    ...sheet.inputs,
    campaign,
    key: sheet.key,
    parcel_ids: sheet.parcels.map((p) => p.urn),
    sigpac,
    applications: sheet.applications,
  };
}

export type Regime = 'rainfed' | 'irrigated';

export interface ParcelGroup {
  id: string;
  crop: string | null;
  regime: Regime | null;
  regimeUnknown: boolean;
  noCrop: boolean;
  parcels: CampaignParcel[];
  areaHa: number | null;
}

const hasValue = (s: Sourced | null | undefined) => !!s && s.value != null && s.provenance !== 'missing';

function areaOf(parcels: CampaignParcel[]): number | null {
  let total = 0;
  for (const p of parcels) {
    if (!hasValue(p.area_ha)) return null;
    total += Number(p.area_ha.value);
  }
  return total;
}

/** Parcels of a campaign grouped by (crop, irrigation regime); the ones without a crop go apart. */
export function groupParcels(parcels: CampaignParcel[]): ParcelGroup[] {
  const groups = new Map<string, ParcelGroup>();
  for (const p of parcels) {
    const crop = hasValue(p.crop) ? String(p.crop.value) : null;
    const regime: Regime | null = p.irrigation_regime === 'rainfed' || p.irrigation_regime === 'irrigated' ? p.irrigation_regime : null;
    const id = crop === null ? 'no-crop' : `${crop}|${regime ?? 'unknown'}`;
    let g = groups.get(id);
    if (!g) {
      g = { id, crop, regime: crop === null ? null : regime, regimeUnknown: crop !== null && regime === null, noCrop: crop === null, parcels: [], areaHa: null };
      groups.set(id, g);
    }
    g.parcels.push(p);
  }
  const out = [...groups.values()];
  for (const g of out) g.areaHa = areaOf(g.parcels);
  return out.sort((a, b) => Number(a.noCrop) - Number(b.noCrop) || a.id.localeCompare(b.id));
}

/** A key (`^[a-z0-9-]{1,40}$`) for a new sheet, unique among `taken`. */
export function sheetKey(eppo: string | null, regime: string | null, taken: Set<string>): string {
  const base = `${eppo ?? 'sheet'}-${regime ?? 'x'}`.toLowerCase().replace(/[^a-z0-9-]/g, '-').slice(0, 34);
  if (!taken.has(base)) return base;
  for (let n = 2; ; n += 1) {
    const k = `${base}-${n}`;
    if (!taken.has(k)) return k;
  }
}

/** Hectares of a sheet; the sum is only for drawing. null when any parcel has no known area. */
export function sheetArea(result: SheetResult | null, parcels: CampaignParcel[], urns: string[]): number | null {
  let total = 0;
  for (const urn of urns) {
    const fromResult = result?.inputs[`parcel.${urn}.area_ha`] as Sourced<number> | undefined;
    const fromParcel = parcels.find((p) => p.id === urn)?.area_ha;
    const s = hasValue(fromResult) ? fromResult : fromParcel;
    if (!hasValue(s)) return null;
    total += Number(s!.value);
  }
  return total;
}

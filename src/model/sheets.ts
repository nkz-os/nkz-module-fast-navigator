import type { CampaignParcel, Plan, PlanSheet, PlanSheetIn, SheetResult, Sourced } from '../api/types';

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

/** What the wizard asks for each group of parcels. `null` = not chosen yet (no silent default). */
export interface GroupManagement {
  included: boolean;
  irrigated: boolean | null;
  tillage: boolean | null;
  rotationYears: number | null;
  residuesBurned: boolean;
  strategy: 1 | 2 | 3 | 4;
  /** Only for the group of parcels with no crop: the EPPO code the user declares. */
  declaredCrop?: string;
}

export const EPPO_RE = /^[A-Z0-9]{5,6}$/;
export const MAX_SHEETS = 20;
export const MAX_PARCELS_PER_SHEET = 200;

/** The starting point: the regime of the data when it is known; everything else is left to choose. */
export function defaultManagement(group: ParcelGroup): GroupManagement {
  return {
    included: !group.noCrop,
    irrigated: group.regime === 'irrigated' ? true : group.regime === 'rainfed' ? false : null,
    tillage: null,
    rotationYears: null,
    residuesBurned: false,
    strategy: 2,
    declaredCrop: group.noCrop ? '' : undefined,
  };
}

const included = (groups: ParcelGroup[], management: Record<string, GroupManagement>) =>
  groups.filter((g) => management[g.id]?.included);

/** i18n keys of what is still missing before the wizard can save. */
export function wizardBlockers(groups: ParcelGroup[], management: Record<string, GroupManagement>): string[] {
  const keys = new Set<string>();
  const chosen = included(groups, management);
  for (const g of chosen) {
    const m = management[g.id];
    if (m.irrigated === null) keys.add('wizard.blocker.regime');
    if (m.tillage === null) keys.add('wizard.blocker.tillage');
    if (m.rotationYears === null || !Number.isInteger(m.rotationYears) || m.rotationYears < 1 || m.rotationYears > 20) {
      keys.add('wizard.blocker.rotation');
    }
    if (g.noCrop && !EPPO_RE.test(m.declaredCrop ?? '')) keys.add('wizard.blocker.crop');
    if (g.parcels.length > MAX_PARCELS_PER_SHEET) keys.add('wizard.blocker.tooManyParcels');
  }
  if (chosen.length > MAX_SHEETS) keys.add('wizard.blocker.tooManySheets');
  return [...keys];
}

/**
 * The full set of sheets to send: the kept existing ones exactly as stored, then one new sheet per
 * included group (its parcels not already in a kept sheet).
 */
export function wizardSheets(groups: ParcelGroup[], management: Record<string, GroupManagement>,
  existing: PlanSheet[], campaign: number): PlanSheetIn[] {
  const out = existing.map((s) => toSheetIn(s, campaign));
  const taken = new Set(existing.map((s) => s.key));
  const used = new Set(existing.flatMap((s) => s.parcels.map((p) => p.urn)));
  for (const g of included(groups, management)) {
    const m = management[g.id];
    const urns = g.parcels.map((p) => p.id).filter((id) => !used.has(id));
    if (urns.length === 0) continue;
    const crop = g.noCrop ? (m.declaredCrop ?? null) : g.crop;
    const key = sheetKey(crop, m.irrigated ? 'irrigated' : 'rainfed', taken);
    taken.add(key);
    out.push({
      campaign, tillage: m.tillage as boolean, irrigated: m.irrigated as boolean,
      rotation_years: m.rotationYears as number, strategy: m.strategy,
      previous_residues_burned: m.residuesBurned,
      crop_eppo: g.noCrop ? (m.declaredCrop ?? null) : null,
      previous_crop_eppo: null, cycle_index: 0, soil_analysis_id: null, nmin_analysis_id: null,
      declared_yields: {}, previous_declared_yields: {}, organic: [],
      water_m3_ha: null, water_quality_id: null, no3_mg_l: null, nuts: null,
      key, parcel_ids: urns, sigpac: {}, applications: [],
    });
  }
  return out;
}

/** The same sheets as stored, with `patch` applied to the one named `key`. */
export function editSheet(plan: Plan, key: string, patch: Partial<PlanSheetIn>): PlanSheetIn[] {
  return plan.sheets.map((s) => {
    const body = toSheetIn(s, plan.campaign);
    return s.key === key ? { ...body, ...patch } : body;
  });
}

/** A calculated sheet that has no previous crop at all (neither declared nor from the crop cycles). */
export function lacksPreviousCrop(sheet: PlanSheet): boolean {
  if (sheet.inputs.previous_crop_eppo != null || !sheet.result) return false;
  const prev = sheet.result.inputs['previous_crop.eppo'] as { value?: unknown } | undefined;
  return prev == null || prev.value == null;
}

/**
 * All the sheets to send when one previous crop is applied to every sheet that lacks one. The
 * current sheet keeps its pending edits (`patch`) and takes the value whatever it had.
 */
export function applyPreviousCrop(plan: Plan, currentKey: string, patch: Partial<PlanSheetIn>,
  value: string): PlanSheetIn[] {
  return plan.sheets.map((s) => {
    const body = toSheetIn(s, plan.campaign);
    if (s.key === currentKey) return { ...body, ...patch, previous_crop_eppo: value };
    return lacksPreviousCrop(s) ? { ...body, previous_crop_eppo: value } : body;
  });
}

/** The short id of a parcel URN: what the soil module reads from `?parcel=`. */
export const shortParcelId = (urn: string) => urn.split(':').pop() ?? urn;

/** Where a missing value is put, by its owner: a link for another module, or a hint. */
export function ownerLink(owner: string, parcelIds: string[], field?: string): { key: string; href?: string } {
  if (owner === 'soil') {
    const first = parcelIds[0];
    return { key: 'ownerLink.soil', href: first ? `/module/soil?parcel=${encodeURIComponent(shortParcelId(first))}&tab=manual` : '/module/soil?tab=manual' };
  }
  if (owner === 'bioorch') return { key: 'ownerLink.bioorch' };
  if (owner === 'plan') return { key: 'ownerLink.plan', href: field ? `#field-${field.split('.')[0]}` : undefined };
  if (owner === 'broker') return { key: 'ownerLink.broker' };
  return { key: 'ownerLink.unknown' };
}

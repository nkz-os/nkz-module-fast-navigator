/** Plans for render tests, built from the backend's own fixtures. */
import type { CampaignParcels, Plan, PlanSheet, SheetResult } from '../api/types';
import parcelsFx from './fixtures/campaign-parcels.json';
import completeFx from './fixtures/sheet-result-complete.json';
import incompleteFx from './fixtures/sheet-result-incomplete.json';

export const COMPLETE = completeFx as unknown as SheetResult;
export const INCOMPLETE = incompleteFx as unknown as SheetResult;
export const PARCELS = parcelsFx as unknown as CampaignParcels;
export const URN = 'urn:ngsi-ld:AgriParcel:p1';

export const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v));

export function makeSheet(over: Partial<PlanSheet> = {}): PlanSheet {
  return {
    key: 'trzax-rainfed', seq: 0,
    inputs: {
      campaign: 2027, tillage: true, irrigated: false, rotation_years: 4, strategy: 2,
      previous_residues_burned: false, crop_eppo: null, previous_crop_eppo: null, cycle_index: 0,
      soil_analysis_id: null, nmin_analysis_id: null, declared_yields: {}, previous_declared_yields: {},
      organic: [], water_m3_ha: null, water_quality_id: null, no3_mg_l: null, nuts: null,
    },
    overrides: [], parcels: [{ urn: URN, sigpac: null }], applications: [], n_adjustment: null,
    result: clone(COMPLETE), applications_summary: null, ...over,
  };
}

export function makePlan(over: Partial<Plan> = {}): Plan {
  return {
    id: 'plan-1', farm: 'tenant', campaign: 2027, version: 1, state: 'draft', row_version: 3, supersedes: null,
    calc_fresh: true, calculated_at: null, rain_normal: null, sheets: [makeSheet()], findings: [],
    declarations: { vulnerable_zone: null, vulnerable_zone_source: null, voluntary_digital_notebook: false, irrigated_spring_2026: null },
    signature: null, signed_at: null, snapshot_sha256: null, rules_version: 'r1', ...over,
  };
}

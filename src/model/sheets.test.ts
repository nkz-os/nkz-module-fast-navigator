import { describe, expect, it } from 'vitest';
import type { CampaignParcels, PlanSheet, SheetResult } from '../api/types';
import parcelsFx from '../test/fixtures/campaign-parcels.json';
import completeFx from '../test/fixtures/sheet-result-complete.json';
import { groupParcels, sheetArea, sheetKey, toSheetIn } from './sheets';

const PARCELS = (parcelsFx as unknown as CampaignParcels).parcels;
const RESULT = completeFx as unknown as SheetResult;

const SHEET: PlanSheet = {
  key: 'trzax-rainfed', seq: 0,
  inputs: {
    campaign: 2027, tillage: true, irrigated: false, rotation_years: 4, strategy: 2,
    previous_residues_burned: false, crop_eppo: 'TRZAX', previous_crop_eppo: null, cycle_index: 0,
    soil_analysis_id: 'a1', nmin_analysis_id: null, declared_yields: { '2025': 5200 },
    previous_declared_yields: {}, organic: [{ material: 'm', rate_t_ha: 20, n_pct: 0.6, p2o5_pct: 0.3, k2o_pct: 0.5 }],
    water_m3_ha: null, water_quality_id: null, no3_mg_l: null, nuts: 'ES22',
  },
  overrides: [{ param: 'soil.ph', value: 7, reason: 'r', user_id: 'u', at: 't' }],
  parcels: [{ urn: 'urn:ngsi-ld:AgriParcel:p1', sigpac: '31:201:0:0:12:45:1' }, { urn: 'urn:ngsi-ld:AgriParcel:p2', sigpac: null }],
  applications: [{ planned_date: '2026-10-25', kind: 'mineral' }, { planned_date: '2027-02-20', kind: 'mineral' }],
  n_adjustment: null, result: null, applications_summary: null,
};

describe('toSheetIn', () => {
  it('round-trips every input, parcel, sigpac and application, and never sends overrides', () => {
    const out = toSheetIn(SHEET, 2027);
    expect(out).toEqual({
      ...SHEET.inputs, key: 'trzax-rainfed',
      parcel_ids: ['urn:ngsi-ld:AgriParcel:p1', 'urn:ngsi-ld:AgriParcel:p2'],
      sigpac: { 'urn:ngsi-ld:AgriParcel:p1': '31:201:0:0:12:45:1' },
      applications: SHEET.applications,
    });
    expect('overrides' in out).toBe(false);
  });
});

describe('groupParcels', () => {
  it('puts the parcels without a crop apart and flags an unknown regime', () => {
    const groups = groupParcels(PARCELS);
    expect(groups.map((g) => [g.crop, g.noCrop, g.regimeUnknown, g.parcels.length])).toEqual([
      ['TRZAX', false, true, 1],
      [null, true, false, 1],
    ]);
    expect(groups[0].areaHa).toBe(10);
  });
  it('groups by crop and regime', () => {
    const base = PARCELS[1];
    const mk = (id: string, regime: 'rainfed' | 'irrigated') => ({ ...base, id, irrigation_regime: regime });
    const groups = groupParcels([mk('a', 'rainfed'), mk('b', 'irrigated'), mk('c', 'rainfed')]);
    expect(groups.map((g) => [g.regime, g.parcels.length, g.regimeUnknown])).toEqual([['irrigated', 1, false], ['rainfed', 2, false]]);
  });
});

describe('sheetKey', () => {
  it('is unique among the taken ones', () => {
    expect(sheetKey('TRZAX', 'rainfed', new Set(['trzax-rainfed']))).toBe('trzax-rainfed-2');
    expect(sheetKey('TRZAX', 'rainfed', new Set())).toBe('trzax-rainfed');
    expect(sheetKey(null, null, new Set())).toMatch(/^[a-z0-9-]{1,40}$/);
  });
});

describe('sheetArea', () => {
  const urn = 'urn:ngsi-ld:AgriParcel:p1';
  it('sums the areas of the result', () => {
    expect(sheetArea(RESULT, PARCELS, [urn])).toBe(10);
  });
  it('is null when one area is missing', () => {
    expect(sheetArea(RESULT, PARCELS, [urn, 'urn:ngsi-ld:AgriParcel:nope'])).toBeNull();
  });
});

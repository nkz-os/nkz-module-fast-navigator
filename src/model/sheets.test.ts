import { describe, expect, it } from 'vitest';
import type { CampaignParcels, Plan, PlanSheet, SheetResult } from '../api/types';
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

import { defaultManagement, wizardBlockers, wizardSheets, type GroupManagement } from './sheets';

describe('wizard', () => {
  const groups = groupParcels(PARCELS);
  const wheat = groups[0];
  const chosen = (over: Partial<GroupManagement> = {}): Record<string, GroupManagement> =>
    ({ [wheat.id]: { ...defaultManagement(wheat), irrigated: false, tillage: true, rotationYears: 4, ...over } });

  it('asks for the regime, the tillage and the rotation: nothing is assumed', () => {
    const blockers = wizardBlockers(groups, { [wheat.id]: defaultManagement(wheat) });
    expect(blockers).toEqual(expect.arrayContaining(['wizard.blocker.regime', 'wizard.blocker.tillage', 'wizard.blocker.rotation']));
  });
  it('a group with a known regime does not ask for it again', () => {
    const rainfed = groupParcels([{ ...PARCELS[1], irrigation_regime: 'rainfed' }])[0];
    expect(wizardBlockers([rainfed], { [rainfed.id]: defaultManagement(rainfed) })).not.toContain('wizard.blocker.regime');
  });
  it('is clear once everything is chosen', () => {
    expect(wizardBlockers(groups, chosen())).toEqual([]);
    expect(wizardBlockers(groups, chosen({ rotationYears: null }))).toContain('wizard.blocker.rotation');
  });
  it('the group without a crop needs a valid declared crop to be included', () => {
    const none = groups[1];
    const m = { ...chosen(), [none.id]: { ...defaultManagement(none), included: true, irrigated: false, tillage: true, rotationYears: 3 } };
    expect(wizardBlockers(groups, m)).toContain('wizard.blocker.crop');
    m[none.id].declaredCrop = 'HORVX';
    expect(wizardBlockers(groups, m)).toEqual([]);
  });
  it('keeps an existing sheet identical and adds the new one with strategy 2 and no applications', () => {
    const elsewhere: PlanSheet = { ...SHEET, parcels: [{ urn: 'urn:ngsi-ld:AgriParcel:p9', sigpac: null }] };
    const sheets = wizardSheets(groups, chosen(), [elsewhere], 2027);
    expect(sheets[0]).toEqual(toSheetIn(elsewhere, 2027));
    expect(sheets).toHaveLength(2);
    expect(sheets[1]).toMatchObject({
      key: 'trzax-rainfed-2', strategy: 2, previous_residues_burned: false, applications: [], sigpac: {},
      parcel_ids: ['urn:ngsi-ld:AgriParcel:p1'], irrigated: false, tillage: true, rotation_years: 4, crop_eppo: null,
    });
  });
  it('does not put a parcel in two sheets', () => {
    const taken: PlanSheet = { ...SHEET, parcels: [{ urn: 'urn:ngsi-ld:AgriParcel:p1', sigpac: null }] };
    expect(wizardSheets(groups, chosen(), [taken], 2027)).toHaveLength(1);
  });
});

import { applyPreviousCrop, editSheet, lacksPreviousCrop, ownerLink, shortParcelId } from './sheets';

describe('editSheet', () => {
  const plan = {
    campaign: 2027,
    sheets: [SHEET, { ...SHEET, key: 'other', parcels: [{ urn: 'urn:ngsi-ld:AgriParcel:p3', sigpac: null }], applications: [] }],
  } as unknown as Plan;
  it('changes only the named sheet and keeps the others as stored', () => {
    const out = editSheet(plan, 'other', { water_m3_ha: 2500 });
    expect(out[0]).toEqual(toSheetIn(plan.sheets[0], 2027));
    expect(out[1]).toEqual({ ...toSheetIn(plan.sheets[1], 2027), water_m3_ha: 2500 });
  });
  it('sending the sheets unchanged loses no input, parcel, sigpac or application', () => {
    expect(editSheet(plan, 'nothing', {})).toEqual(plan.sheets.map((s) => toSheetIn(s, 2027)));
  });
});

describe('ownerLink', () => {
  it('soil reads the short parcel id, as the soil module does', () => {
    expect(shortParcelId('urn:ngsi-ld:AgriParcel:p1')).toBe('p1');
    expect(ownerLink('soil', ['urn:ngsi-ld:AgriParcel:p1'])).toEqual({ key: 'ownerLink.soil', href: '/module/soil?parcel=p1&tab=manual' });
  });
  it('the others are text or an anchor', () => {
    expect(ownerLink('bioorch', [])).toEqual({ key: 'ownerLink.bioorch' });
    expect(ownerLink('broker', [])).toEqual({ key: 'ownerLink.broker' });
    expect(ownerLink('plan', [], 'yield.kg_ha')).toEqual({ key: 'ownerLink.plan', href: '#field-yield' });
  });
});

describe('ownerLink without a parcel', () => {
  it('soil still opens the manual analysis form', () => {
    expect(ownerLink('soil', [])).toEqual({ key: 'ownerLink.soil', href: '/module/soil?tab=manual' });
  });
});

describe('previous crop for all sheets', () => {
  const calculated = (key: string, previous: unknown, declared: string | null = null) => ({
    ...SHEET, key, inputs: { ...SHEET.inputs, previous_crop_eppo: declared },
    result: { inputs: { 'previous_crop.eppo': { value: previous, provenance: previous == null ? 'missing' : 'measured' } } },
  }) as unknown as PlanSheet;
  const plan = { campaign: 2027, sheets: [calculated('a', null), calculated('b', null), calculated('c', 'HORVX'),
    calculated('d', 'TRZAX', 'TRZAX'), { ...SHEET, key: 'e', result: null }] } as unknown as Plan;

  it('only a calculated sheet with no previous crop lacks one', () => {
    expect(plan.sheets.map(lacksPreviousCrop)).toEqual([true, true, false, false, false]);
  });
  it('sets the value on the sheets that lack it and on the current one, nothing else', () => {
    const out = applyPreviousCrop(plan, 'a', { water_m3_ha: 10 }, 'fallow');
    expect(out.map((s) => s.previous_crop_eppo)).toEqual(['fallow', 'fallow', null, 'TRZAX', null]);
    expect(out[0].water_m3_ha).toBe(10);
    expect(out[2]).toEqual(toSheetIn(plan.sheets[2], 2027));
    const withRes = applyPreviousCrop(plan, 'a', {}, 'HORVX', 'removed');
    expect(withRes.map((s) => s.previous_residues)).toEqual(['removed', 'removed', undefined, undefined, undefined]);
  });
});

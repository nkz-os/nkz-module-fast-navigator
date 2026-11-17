import { describe, expect, it } from 'vitest';
import type { ZoneDosesResponse } from '../api/types';
import { base64UrlEncode, basisKey, buildPrescriptionLink, buildZoneDosesRequest, noticeView, parseNumber, zoneMark, unavailableKey, zoneLabel, zoningLabel } from './zoneDoses';

const BASE = { parcelUrn: 'urn:ngsi-ld:AgriParcel:parcel-1', runId: 'run-1', strategy: 'uniform' as const, capText: '20', targetText: '60', productName: '', nPctText: '' };

describe('parseNumber', () => {
  it('accepts a decimal comma and rejects empty or non-numeric text', () => {
    expect(parseNumber('60,5')).toBe(60.5);
    expect(parseNumber(' 12 ')).toBe(12);
    expect(parseNumber('')).toBeNull();
    expect(parseNumber('abc')).toBeNull();
    expect(parseNumber('1e999')).toBeNull();
  });
});

describe('buildZoneDosesRequest', () => {
  it('builds the body the API takes, with the technician dose and no product', () => {
    expect(buildZoneDosesRequest(BASE)).toEqual({
      ok: true,
      body: { parcel_urn: BASE.parcelUrn, zoning_run_id: 'run-1', strategy: 'uniform', cap_pct: 20, target: { n_kg_ha: 60 } },
    });
  });
  it('adds the product when both its name and richness are given', () => {
    const r = buildZoneDosesRequest({ ...BASE, productName: ' Nitrate 27 ', nPctText: '27' });
    expect(r).toMatchObject({ ok: true, body: { target: { n_kg_ha: 60, product: { name: 'Nitrate 27', n_pct: 27 } } } });
  });
  it('a product given by halves is a problem, not a silent drop', () => {
    expect(buildZoneDosesRequest({ ...BASE, productName: 'Nitrate' })).toEqual({ ok: false, problem: 'product' });
    expect(buildZoneDosesRequest({ ...BASE, nPctText: '27' })).toEqual({ ok: false, problem: 'product' });
    expect(buildZoneDosesRequest({ ...BASE, productName: 'x', nPctText: '0' })).toEqual({ ok: false, problem: 'product' });
    expect(buildZoneDosesRequest({ ...BASE, productName: 'x', nPctText: '101' })).toEqual({ ok: false, problem: 'product' });
  });
  it('the dose must be a number above 0 up to 1000, never defaulted', () => {
    for (const bad of ['', '0', '-5', 'x', '1001']) expect(buildZoneDosesRequest({ ...BASE, targetText: bad })).toEqual({ ok: false, problem: 'target' });
  });
  it('the cap is 0 to 30', () => {
    expect(buildZoneDosesRequest({ ...BASE, capText: '0' })).toMatchObject({ ok: true, body: { cap_pct: 0 } });
    expect(buildZoneDosesRequest({ ...BASE, capText: '30' })).toMatchObject({ ok: true, body: { cap_pct: 30 } });
    for (const bad of ['', '-1', '31', 'x']) expect(buildZoneDosesRequest({ ...BASE, capText: bad })).toEqual({ ok: false, problem: 'cap' });
  });
  it('sends nothing without a zoning or a parcel', () => {
    expect(buildZoneDosesRequest({ ...BASE, runId: null })).toEqual({ ok: false, problem: 'noZoning' });
    expect(buildZoneDosesRequest({ ...BASE, parcelUrn: null })).toEqual({ ok: false, problem: 'noZoning' });
  });
});

describe('labels', () => {
  it('names a zoning by method, date and zone count; a manual one is said', () => {
    const z = { run_id: 'a', method: 'vegetationIndex', variable: 'NDVI', date: '2026-10-14', zone_count: 4, has_vegetation_value: true };
    expect(zoningLabel(z, 'es')).toEqual({ key: 'zoneDoses.zoning.vegetationIndex', params: { variable: 'NDVI', date: '14/10/2026', count: 4 } });
    expect(zoningLabel({ ...z, method: 'manual', variable: null, date: null, has_vegetation_value: false }, 'es'))
      .toEqual({ key: 'zoneDoses.zoning.manual', params: { date: '—', count: 4 } });
    expect(zoningLabel({ ...z, method: null }, 'es').key).toBe('zoneDoses.zoning.other');
  });
  it('a zone without a label is numbered by its rank, else by position', () => {
    expect(zoneLabel({ label: 'Alta', rank: 1 }, 0)).toEqual({ text: 'Alta' });
    expect(zoneLabel({ label: null, rank: 3 }, 0)).toEqual({ key: 'zoneDoses.zoneN', params: { n: 3 } });
    expect(zoneLabel({ label: null, rank: null }, 1)).toEqual({ key: 'zoneDoses.zoneN', params: { n: 2 } });
  });
  it('a zone with a vigor level is named from the level, whatever its stored label', () => {
    expect(zoneLabel({ label: 'high', rank: 1, level: 'high' }, 0)).toEqual({ key: 'zoneDoses.level.high', params: { n: 1 } });
    expect(zoneLabel({ label: 'x', rank: 4, level: 'critical' }, 3)).toMatchObject({ key: 'zoneDoses.level.critical' });
    expect(zoneLabel({ label: 'Alta', rank: 1, level: null }, 0)).toEqual({ text: 'Alta' });
  });
  it('an unknown level is never shown: it falls back to "Zone n"', () => {
    expect(zoneLabel({ label: 'extreme', rank: 2, level: 'extreme' }, 0)).toEqual({ key: 'zoneDoses.zoneN', params: { n: 2 } });
    expect(zoneLabel({ label: 'x', rank: null, level: '' }, 4)).toEqual({ key: 'zoneDoses.zoneN', params: { n: 5 } });
  });
  it('a multi-date zoning is named with its variable, image date and zone count', () => {
    const z = { run_id: 'm', method: 'vegetationIndexMultiDate', variable: 'NDVI', date: '2026-10-14', image_date: '2026-05-20', zone_count: 4, has_vegetation_value: true };
    expect(zoningLabel(z, 'es')).toEqual({ key: 'zoneDoses.zoning.vegetationIndexMultiDate', params: { variable: 'NDVI', date: '20/05/2026', count: 4 } });
    expect(zoningLabel({ ...z, image_date: undefined }, 'es').params.date).toBe('14/10/2026');
  });
  it('maps the origin of a figure and the unavailable reason to keys', () => {
    expect(basisKey('vigor')).toBe('zoneDoses.basis.vigor');
    expect(basisKey('sheet')).toBe('zoneDoses.basis.sheet');
    expect(basisKey('zone_soil')).toBe('zoneDoses.basis.zone_soil');
    expect(unavailableKey('single_zone')).toBe('zoneDoses.unavailable.single_zone');
  });
  it('a notice keeps its params, with dates and hectares written for the language', () => {
    expect(noticeView({ code: 'zoning_image_old', params: { date: '2026-09-01', days: 40 } }, 'es'))
      .toEqual({ key: 'zoneDoses.notice.zoning_image_old', params: { date: '01/09/2026', days: '40' } });
    expect(noticeView({ code: 'zones_do_not_cover_parcel', params: { rest_ha: 2.5, parcel_ha: 10 } }, 'en'))
      .toEqual({ key: 'zoneDoses.notice.zones_do_not_cover_parcel', params: { rest_ha: '2.5', parcel_ha: '10.0' } });
    expect(noticeView({ code: 'total_above_planned' }, 'es')).toEqual({ key: 'zoneDoses.notice.total_above_planned', params: {} });
  });
});

describe('zone soil notices and mark', () => {
  it('writes the zone-soil notice params for the language', () => {
    expect(noticeView({ code: 'zone_soil_mixed_dates', params: { zone: 'Z1', p_date: '2026-09-15', k_date: '2026-09-20' } }, 'es'))
      .toEqual({ key: 'zoneDoses.notice.zone_soil_mixed_dates', params: { zone: 'Z1', p_date: '15/09/2026', k_date: '20/09/2026' } });
    expect(noticeView({ code: 'zone_nmin_other_date', params: { zone: 'Z1', date: '2026-09-15' } }, 'es').params.date).toBe('15/09/2026');
    expect(noticeView({ code: 'zone_soil_missing', params: { zones: ['Z1', 'Z2'] } }, 'es').params.zones).toBe('Z1, Z2');
  });
  it('names the zones of a notice as the table does', () => {
    const name = (x: string) => (x === 'urn:z1' ? 'Vigor alto' : x);
    expect(noticeView({ code: 'zone_dose_floored', params: { zone: 'urn:z1' } }, 'es', name).params.zone).toBe('Vigor alto');
    expect(noticeView({ code: 'zone_soil_missing', params: { zones: ['urn:z1', 'Zona 3'] } }, 'es', name).params.zones).toBe('Vigor alto, Zona 3');
  });
  it('first-pass-only picks one of two texts from applied', () => {
    expect(noticeView({ code: 'zone_nmin_first_pass_only', params: { applied: true } }, 'es').key).toBe('zoneDoses.notice.zone_nmin_first_pass_only_applied');
    expect(noticeView({ code: 'zone_nmin_first_pass_only', params: { applied: false } }, 'es').key).toBe('zoneDoses.notice.zone_nmin_first_pass_only_not_applied');
  });
  const row = (o: object) => ({ basis: 'vigor' as const, soil_analysis: null, ...o });
  it('the mark: zone analysis with date and samples, both dates when P and K differ, else the parcel mean', () => {
    const sa = { id: 'a', date: '2026-09-20', n_samples: 2, p_date: '2026-09-15', k_date: '2026-09-15' };
    expect(zoneMark(row({ basis: 'zone_soil', soil_analysis: { ...sa, date: '2026-09-15' } }), 'es'))
      .toEqual({ key: 'zoneDoses.mark.zoneSoil', params: { date: '15/09/2026', count: 2 } });
    expect(zoneMark(row({ basis: 'zone_soil', soil_analysis: { ...sa, k_date: '2026-09-20' } }), 'es'))
      .toEqual({ key: 'zoneDoses.mark.zoneSoilPK', params: { p: '15/09/2026', k: '20/09/2026', count: 2 } });
    expect(zoneMark(row({}), 'es')).toEqual({ key: 'zoneDoses.mark.parcel', params: {} });
  });
  it('hides the sample count when it is 0 or missing', () => {
    const sa = { id: 'a', date: '2026-09-15', p_date: '2026-09-15', k_date: '2026-09-15' };
    expect(zoneMark(row({ basis: 'zone_soil', soil_analysis: { ...sa, n_samples: 0 } }), 'es'))
      .toEqual({ key: 'zoneDoses.mark.zoneSoilNoCount', params: { date: '15/09/2026' } });
    expect(zoneMark(row({ basis: 'zone_soil', soil_analysis: { ...sa, k_date: '2026-09-20' } }), 'es').key).toBe('zoneDoses.mark.zoneSoilPKNoCount');
  });
  it('says which nutrient is the parcel mean when the zone has no analysis of it', () => {
    const sa = { id: 'a', date: '2026-09-15', n_samples: 1, p_date: '2026-09-15', k_date: null };
    expect(zoneMark(row({ basis: 'zone_soil', soil_analysis: sa }), 'es').parcelFor).toEqual(['zoneDoses.mark.kParcel']);
    expect(zoneMark(row({ basis: 'zone_soil', soil_analysis: { ...sa, p_date: null } }), 'es').parcelFor).toEqual(['zoneDoses.mark.pParcel', 'zoneDoses.mark.kParcel']);
    expect(zoneMark(row({ basis: 'zone_soil', soil_analysis: { ...sa, k_date: '2026-09-15' } }), 'es').parcelFor).toBeUndefined();
  });
  it('carries the zone own Nmin only for a zone-soil zone', () => {
    const sa = { id: 'a', date: '2026-09-15', n_samples: 1, p_date: null, k_date: null };
    expect(zoneMark(row({ basis: 'zone_soil', nmin_kg_ha: 29.7, soil_analysis: sa }), 'es').nmin).toBe('30');
    expect(zoneMark(row({ basis: 'zone_soil', nmin_kg_ha: null, soil_analysis: sa }), 'es').nmin).toBeUndefined();
    expect(zoneMark(row({ nmin_kg_ha: 29.7 }), 'es').nmin).toBeUndefined();
  });
});

const RES: ZoneDosesResponse = {
  plan: { id: 'plan-1', state: 'calculated', campaign: 2027 },
  sheet: { key: 'wheat', n_kg_ha: null, crop: { eppo: 'TRZAX', n_fixing: false } },
  zoning: { run_id: 'run-1', method: 'vegetationIndex', variable: 'NDVI', date: '2026-10-14', zone_count: 2 },
  strategy: 'potential', strategy_unavailable: null,
  target: { n_kg_ha: 60, source: 'given', product: { name: 'Nitrato álcali 27 %', n_pct: 27 } },
  cap: { pct: 20, min_n_kg_ha: 48, max_n_kg_ha: 72 },
  zones: [
    { zone_id: 'urn:ngsi-ld:AgriManagementZone:z1', label: null, rank: 1, area_ha: 2, basis: 'vigor', relative_vigor: 1.2, factor: 1.2, capped: false, n_kg_ha: 72, product_kg_ha: 266.67, soil_analysis: null, missing: [] },
    { zone_id: 'urn:ngsi-ld:AgriManagementZone:z2', label: null, rank: 2, area_ha: 2, basis: 'vigor', relative_vigor: 0.8, factor: 0.8, capped: false, n_kg_ha: 48, product_kg_ha: 177.78, soil_analysis: null, missing: [] },
  ],
  rest: { area_ha: 1, n_kg_ha: 60, product_kg_ha: 222.22 },
  totals: { area_ha: 5, n_kg: 300, mean_n_kg_ha: 60, uniform_n_kg: 300 },
  notices: [], units: { n: 'kg N/ha', product: 'kg/ha' }, versions: {},
};
const PARCEL = 'urn:ngsi-ld:AgriParcel:parcel-1';

function decode(path: string) {
  const q = new URL(path, 'https://x.invalid').searchParams;
  const b64 = q.get('vra') as string;
  expect(b64).toMatch(/^[A-Za-z0-9_-]+$/);
  const std = b64.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (b64.length % 4)) % 4);
  const bin = atob(std);
  return { q, json: JSON.parse(new TextDecoder().decode(Uint8Array.from(bin, (c) => c.charCodeAt(0)))) };
}

describe('base64UrlEncode', () => {
  it('uses the URL-safe alphabet without padding', () => {
    expect(base64UrlEncode('\u00fb\u00ff\u00fe')).toBe('w7vDv8O-');
    expect(base64UrlEncode('a')).toBe('YQ');
    expect(base64UrlEncode('?>>')).toBe('Pz4-');
  });
});

describe('buildPrescriptionLink', () => {
  it('round-trips the answer: rates by zone id, rest, run, product, applied strategy and origin; accents survive', () => {
    const r = buildPrescriptionLink({ res: RES, parcelUrn: PARCEL, current: true });
    if (!r.ok) throw new Error('expected a link');
    expect(r.path.startsWith('/gis-routing?view=work&parcel=urn%3Angsi-ld%3AAgriParcel%3Aparcel-1&vra=')).toBe(true);
    const { q, json } = decode(r.path);
    expect(q.get('view')).toBe('work');
    expect(q.get('parcel')).toBe(PARCEL);
    expect(json).toEqual({
      v: 1, source: 'fast', zoning_run_id: 'run-1', unit: 'kg_ha', product: 'Nitrato álcali 27 %',
      zone_rates: { 'urn:ngsi-ld:AgriManagementZone:z1': 266.67, 'urn:ngsi-ld:AgriManagementZone:z2': 177.78 },
      rest_rate: 222.22,
      origin: { plan: 'plan-1', sheet: 'wheat', strategy: 'potential', n_kg_ha: 60 },
    });
  });

  it('sends the strategy actually applied: uniform when the requested one was unavailable', () => {
    const r = buildPrescriptionLink({ res: { ...RES, strategy_unavailable: 'single_zone' }, parcelUrn: PARCEL, current: true });
    if (!r.ok) throw new Error('expected a link');
    expect(decode(r.path).json.origin.strategy).toBe('uniform');
  });

  it('gives a reason, never a partial link', () => {
    const why = (res: ZoneDosesResponse, current = true) => { const r = buildPrescriptionLink({ res, parcelUrn: PARCEL, current }); return r.ok ? 'ok' : r.reason; };
    expect(why(RES, false)).toBe('stale');
    expect(why({ ...RES, target: { ...RES.target, product: null } })).toBe('noProduct');
    expect(why({ ...RES, zones: [{ ...RES.zones[0], product_kg_ha: null }, RES.zones[1]] })).toBe('missingRate');
    expect(why({ ...RES, rest: { ...RES.rest, product_kg_ha: null } })).toBe('missingRate');
    expect(why({ ...RES, target: { ...RES.target, n_kg_ha: null } })).toBe('missingRate');
    expect(why({ ...RES, zones: [] })).toBe('missingRate');
  });

  it('allows 50 zones and refuses 51', () => {
    const zones = (n: number) => Array.from({ length: n }, (_, i) => ({ ...RES.zones[0], zone_id: `z${i}` }));
    expect(buildPrescriptionLink({ res: { ...RES, zones: zones(50) }, parcelUrn: PARCEL, current: true }).ok).toBe(true);
    expect(buildPrescriptionLink({ res: { ...RES, zones: zones(51) }, parcelUrn: PARCEL, current: true })).toEqual({ ok: false, reason: 'tooManyZones' });
  });
});

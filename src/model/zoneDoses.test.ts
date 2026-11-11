import { describe, expect, it } from 'vitest';
import { basisKey, buildZoneDosesRequest, noticeView, parseNumber, unavailableKey, zoneLabel, zoningLabel } from './zoneDoses';

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

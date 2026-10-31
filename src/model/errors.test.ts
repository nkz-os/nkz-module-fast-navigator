import { describe, expect, it } from 'vitest';
import { FastApiError } from '../api/client';
import { errorView } from './errors';

const e = (status: number, body: unknown) => errorView(new FastApiError(status, body));

describe('errorView', () => {
  it('401', () => expect(e(401, null).key).toBe('error.session'));
  it('403', () => expect(e(403, { error: 'forbidden' }).key).toBe('error.forbidden'));
  it('404 not_found goes back to the list', () => {
    expect(e(404, { error: 'not_found', detail: 'plan x' })).toMatchObject({ key: 'error.planNotFound', backToList: true });
  });
  it('404 parcel_not_found names the parcel', () => {
    expect(e(404, { error: 'parcel_not_found', detail: 'urn:x' })).toMatchObject({ key: 'error.parcelNotFound', params: { urn: 'urn:x' } });
  });
  it('409 conflict reloads', () => expect(e(409, { error: 'conflict' })).toMatchObject({ key: 'error.conflict', reload: true }));
  it.each(['stale_calculation', 'blocking_findings', 'advice_required', 'not_allowed'])('409 %s', (code) => {
    expect(e(409, { error: code, rules: ['r1'] }).key).toBe(`error.transition.${code}`);
  });
  it('409 blocking_findings carries the rules', () => expect(e(409, { error: 'blocking_findings', rules: ['r1'] }).rules).toEqual(['r1']));
  it('422 maps fields by location without the body prefix', () => {
    const v = e(422, { detail: [{ loc: ['body', 'sheets', 0, 'rotation_years'], msg: 'bad' }] });
    expect(v.key).toBe('error.invalid');
    expect(v.fieldErrors).toEqual({ 'sheets.0.rotation_years': 'bad' });
  });
  it('502 and 504 are gateway timeouts', () => {
    expect(e(502, null).key).toBe('error.gatewayTimeout');
    expect(e(504, null).key).toBe('error.gatewayTimeout');
  });
  it('503 names the normalised source', () => {
    expect(e(503, { error: 'source_unavailable', source: 'broker:crop-cycles', detail: 'x' }))
      .toMatchObject({ key: 'error.sourceUnavailable', params: { source: 'source.broker_crop_cycles' } });
    expect(e(503, { error: 'source_unavailable', source: 'weather-api' }).params.source).toBe('source.weather_api');
  });
  it('anything else is generic', () => {
    expect(e(500, null).key).toBe('error.generic');
    expect(errorView(new TypeError('network')).key).toBe('error.generic');
  });
});

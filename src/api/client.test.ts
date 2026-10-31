import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FastApiError } from './client';
import { fetchPlanPdf, listPlans } from './fast';

const fetchMock = vi.fn();
beforeEach(() => {
  (globalThis as Record<string, unknown>).window = { __ENV__: { VITE_API_URL: 'https://api.example/' } };
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => { fetchMock.mockReset(); vi.unstubAllGlobals(); delete (globalThis as Record<string, unknown>).window; });

const reply = (status: number, body: unknown) =>
  fetchMock.mockResolvedValueOnce({ ok: status < 400, status, text: async () => (body === null ? '' : JSON.stringify(body)) });

describe('request', () => {
  it('uses the runtime origin and sends the session cookie', async () => {
    reply(200, []);
    await listPlans(2027);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('https://api.example/api/fast/plans?campaign=2027');
    expect(init.credentials).toBe('include');
    expect(init.headers).toBeUndefined();
  });

  it('turns a 503 into an error that names the source', async () => {
    reply(503, { error: 'source_unavailable', source: 'broker:crop-cycles', detail: 'x' });
    const e = await listPlans(2027).catch((x) => x);
    expect(e).toBeInstanceOf(FastApiError);
    expect([e.status, e.code, e.source]).toEqual([503, 'source_unavailable', 'broker:crop-cycles']);
  });

  it('keeps the location of a validation error', async () => {
    reply(422, { detail: [{ loc: ['body', 'sheets', 0, 'rotation_years'], msg: 'bad', type: 'x' }] });
    const e = await listPlans(2027).catch((x) => x);
    expect(e.fields[0].loc).toEqual(['body', 'sheets', 0, 'rotation_years']);
  });

  it('keeps the rules of a blocked transition', async () => {
    reply(409, { error: 'blocking_findings', detail: 'd', rules: ['ES-RD1051-6.1'] });
    const e = await listPlans(2027).catch((x) => x);
    expect(e.rules).toEqual(['ES-RD1051-6.1']);
  });

  it('survives a gateway answer that is not JSON', async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 502, text: async () => '<html>' });
    const e = await listPlans(2027).catch((x) => x);
    expect([e.status, e.code]).toEqual([502, null]);
  });
});

describe('fetchPlanPdf', () => {
  it('decodes the JSON envelope into a PDF blob', async () => {
    reply(200, { filename: 'fast-plan-2027-v1.pdf', media_type: 'application/pdf', content_base64: btoa('%PDF-1.7 x') });
    const { filename, blob } = await fetchPlanPdf('p1', 'es');
    expect(fetchMock.mock.calls[0][0]).toBe('https://api.example/api/fast/plans/p1/pdf?lang=es&envelope=json');
    expect(filename).toBe('fast-plan-2027-v1.pdf');
    expect(blob.type).toBe('application/pdf');
    expect((await blob.text()).startsWith('%')).toBe(true);
  });
});

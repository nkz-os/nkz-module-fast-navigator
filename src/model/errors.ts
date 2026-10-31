import { FastApiError } from '../api/client';

export interface ErrorView {
  key: string;
  params: Record<string, string>;
  reload?: true;
  backToList?: true;
  fieldErrors?: Record<string, string>;
  rules?: string[];
}

/** `broker:crop-cycles` -> `broker_crop_cycles`: a `:` is the namespace separator of i18next. */
export const normalizeId = (id: string) => id.toLowerCase().replace(/[^a-z0-9]/g, '_');

const TRANSITIONS = new Set(['stale_calculation', 'blocking_findings', 'advice_required', 'not_allowed']);

export function errorView(e: unknown): ErrorView {
  if (!(e instanceof FastApiError)) return { key: 'error.generic', params: {} };
  const { status, code } = e;
  if (status === 401) return { key: 'error.session', params: {} };
  if (status === 403) return { key: 'error.forbidden', params: {} };
  if (status === 404 && code === 'parcel_not_found') return { key: 'error.parcelNotFound', params: { urn: e.detail ?? '' } };
  if (status === 404 && code === 'not_found') return { key: 'error.planNotFound', params: {}, backToList: true };
  if (status === 409 && code === 'conflict') return { key: 'error.conflict', params: {}, reload: true };
  if (status === 409 && code && TRANSITIONS.has(code)) {
    return { key: `error.transition.${code}`, params: {}, ...(e.rules ? { rules: e.rules } : {}) };
  }
  if (status === 422) {
    const fieldErrors: Record<string, string> = {};
    for (const f of e.fields) {
      const path = (f.loc[0] === 'body' ? f.loc.slice(1) : f.loc).join('.');
      if (!(path in fieldErrors)) fieldErrors[path] = f.msg;
    }
    return { key: 'error.invalid', params: { detail: e.detail ?? '' }, fieldErrors };
  }
  if (status === 502 || status === 504) return { key: 'error.gatewayTimeout', params: {} };
  if (status === 503 && code === 'source_unavailable') {
    return { key: 'error.sourceUnavailable', params: { source: `source.${normalizeId(e.source ?? 'unknown')}`, detail: e.detail ?? '' } };
  }
  return { key: 'error.generic', params: {} };
}

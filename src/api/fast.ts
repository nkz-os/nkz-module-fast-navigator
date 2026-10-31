import type {
  CampaignParcels, PdfEnvelope, Plan, PlanListItem, PlanSheetIn,
} from './types';
import type { SourceCrop } from '../model/crops';
import { apiOrigin, request, requestUrl, FastApiError } from './client';

export const listPlans = (campaign: number, signal?: AbortSignal) =>
  request<PlanListItem[]>('GET', `/plans?campaign=${campaign}`, undefined, signal);

export const createPlan = (campaign: number) =>
  request<Plan>('POST', '/plans', { campaign, farm: 'tenant' });

export const getPlan = (id: string, signal?: AbortSignal) =>
  request<Plan>('GET', `/plans/${encodeURIComponent(id)}`, undefined, signal);

export const putSheets = (id: string, rowVersion: number, sheets: PlanSheetIn[]) =>
  request<Plan>('PUT', `/plans/${encodeURIComponent(id)}/sheets`, { row_version: rowVersion, sheets });

export const calculatePlan = (id: string, rowVersion: number) =>
  request<Plan>('POST', `/plans/${encodeURIComponent(id)}/calculate`, { row_version: rowVersion });

/** Needs a plan with saved sheets; answers with the whole plan (`rain_normal` filled). */
export const storeRainNormal = (id: string) =>
  request<Plan>('POST', `/plans/${encodeURIComponent(id)}/rain-normal`);

const overridePath = (id: string, key: string, param: string) =>
  `/plans/${encodeURIComponent(id)}/sheets/${encodeURIComponent(key)}/overrides/${encodeURIComponent(param)}`;

export const putOverride = (id: string, key: string, param: string, rowVersion: number,
  value: number | string | boolean, reason: string) =>
  request<Plan>('PUT', overridePath(id, key, param), { row_version: rowVersion, value, reason });

export const deleteOverride = (id: string, key: string, param: string, rowVersion: number) =>
  request<Plan>('DELETE', `${overridePath(id, key, param)}?row_version=${rowVersion}`);

export const campaignParcels = (campaign: number, signal?: AbortSignal) =>
  request<CampaignParcels>('GET', `/sources/campaigns/${campaign}/parcels`, undefined, signal);

/** Crops the user can pick by name (FaST reads them from BioOrch; 503 when BioOrch is down). */
export const sourceCrops = (signal?: AbortSignal) =>
  request<{ crops: SourceCrop[] }>('GET', '/sources/crops', undefined, signal).then((r) => r.crops);

/** The PDF travels inside a JSON envelope: the gateway proxy only carries JSON. */
export async function fetchPlanPdf(id: string, lang: 'es' | 'en'): Promise<{ filename: string; blob: Blob }> {
  const env = await request<PdfEnvelope>('GET', `/plans/${encodeURIComponent(id)}/pdf?lang=${lang}&envelope=json`);
  const bin = atob(env.content_base64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
  return { filename: env.filename, blob: new Blob([bytes], { type: 'application/pdf' }) };
}

/** Crop name for an EPPO code; null when the code is unknown. */
export async function cropName(eppo: string, lang: string, signal?: AbortSignal): Promise<string | null> {
  const url = `${apiOrigin()}/api/graph/agriculture/crop-name?eppo=${encodeURIComponent(eppo)}&lang=${encodeURIComponent(lang)}`;
  try {
    const r = await requestUrl<{ name?: string | null } | string | null>('GET', url, undefined, signal);
    if (typeof r === 'string') return r;
    return r?.name ?? null;
  } catch (e) {
    if (e instanceof FastApiError && e.status === 404) return null;
    throw e;
  }
}

export interface Attribution { source_id: string; text: string; url?: string | null; licence_url?: string | null }
export const fetchAttributions = (signal?: AbortSignal) =>
  requestUrl<{ attributions: Attribution[] }>('GET', `${apiOrigin()}/api/graph/agriculture/sources/attributions`, undefined, signal);

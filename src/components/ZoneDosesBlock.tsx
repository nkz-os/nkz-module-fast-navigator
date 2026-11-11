import React, { useEffect, useRef, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Badge, Button, FormField, FormGrid, Inline, Input, Select, Stack, Surface } from '@nekazari/ui-kit';
import { sheetZonings, zoneDoses } from '../api/fast';
import type { CampaignParcel, PlanSheet, ZoneDosesResponse, ZoneStrategy } from '../api/types';
import { useLoad } from '../hooks/useLoad';
import { DASH, formatDecimal1, formatDecimal2, formatHa, formatKgHa } from '../model/format';
import { basisKey, buildZoneDosesRequest, noticeView, unavailableKey, zoneLabel, zoningLabel } from '../model/zoneDoses';
import { ErrorBanner } from './ErrorBanner';

const STRATEGIES: ZoneStrategy[] = ['uniform', 'potential', 'compensate'];
const parcelName = (urn: string, parcels: CampaignParcel[]) => {
  const bare = urn.split(':').pop() ?? urn;
  return parcels.find((p) => p.id === urn || p.id === bare)?.name ?? bare;
};

interface Answer { key: string; data: ZoneDosesResponse | null; error: unknown }

/** The answer of the API: the table of zones with the origin of each figure, the totals and the notices. */
export function ZoneDosesResult({ res }: { res: ZoneDosesResponse }) {
  const { t, i18n } = useTranslation('fast-navigator');
  const lang = i18n.language;
  const k1 = (v: number | null | undefined) => formatDecimal1(v, lang);
  return (
    <Stack gap="inline">
      {res.strategy_unavailable && (
        <div role="status" className="rounded-nkz-md border border-nkz-warning bg-nkz-warning-soft p-nkz-inline text-nkz-sm text-nkz-text-primary">
          {t('zoneDoses.unavailableIntro', { strategy: t(`zoneDoses.strategy.${res.strategy}`), reason: t(unavailableKey(res.strategy_unavailable), { defaultValue: res.strategy_unavailable }) })}
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-nkz-sm">
          <thead>
            <tr className="border-b border-nkz-border text-nkz-text-secondary">
              <th className="py-nkz-tight pr-nkz-inline font-medium">{t('zoneDoses.col.zone')}</th>
              <th className="py-nkz-tight pr-nkz-inline font-medium">{t('zoneDoses.col.area')}</th>
              <th className="py-nkz-tight pr-nkz-inline font-medium">{t('zoneDoses.col.vigor')}</th>
              <th className="py-nkz-tight pr-nkz-inline font-medium">{t('zoneDoses.col.origin')}</th>
              <th className="py-nkz-tight pr-nkz-inline font-medium">{t('zoneDoses.col.n')}</th>
              <th className="py-nkz-tight pr-nkz-inline font-medium">{t('zoneDoses.col.product')}</th>
            </tr>
          </thead>
          <tbody>
            {res.zones.map((z, i) => {
              const l = zoneLabel(z, i);
              return (
                <tr key={z.zone_id} className="border-b border-nkz-border text-nkz-text-primary">
                  <td className="py-nkz-tight pr-nkz-inline">{'text' in l ? l.text : t(l.key, l.params)}</td>
                  <td className="py-nkz-tight pr-nkz-inline">{formatHa(z.area_ha, lang)}</td>
                  <td className="py-nkz-tight pr-nkz-inline">{formatDecimal2(z.relative_vigor, lang)}</td>
                  <td className="py-nkz-tight pr-nkz-inline">
                    {t(basisKey(z.basis))}
                    {z.missing.length > 0 && (
                      <span className="block text-nkz-xs text-nkz-warning">{z.missing.map((m) => t(`zoneDoses.missing.${m}`, { defaultValue: m })).join(', ')}</span>
                    )}
                  </td>
                  <td className="py-nkz-tight pr-nkz-inline font-medium">
                    {k1(z.n_kg_ha)} {z.capped && <Badge intent="info">{t('zoneDoses.capped')}</Badge>}
                  </td>
                  <td className="py-nkz-tight pr-nkz-inline">{z.product_kg_ha == null ? DASH : formatKgHa(z.product_kg_ha, lang)}</td>
                </tr>
              );
            })}
            {res.rest.area_ha != null && res.rest.area_ha > 0 && (
              <tr className="border-b border-nkz-border text-nkz-text-primary">
                <td className="py-nkz-tight pr-nkz-inline">{t('zoneDoses.rest')}</td>
                <td className="py-nkz-tight pr-nkz-inline">{formatHa(res.rest.area_ha, lang)}</td>
                <td className="py-nkz-tight pr-nkz-inline">{DASH}</td>
                <td className="py-nkz-tight pr-nkz-inline">{t(basisKey('sheet'))}</td>
                <td className="py-nkz-tight pr-nkz-inline font-medium">{k1(res.rest.n_kg_ha)}</td>
                <td className="py-nkz-tight pr-nkz-inline">{res.rest.product_kg_ha == null ? DASH : formatKgHa(res.rest.product_kg_ha, lang)}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <p className="text-nkz-xs text-nkz-text-muted">{t('zoneDoses.units')}</p>
      <p className="text-nkz-sm text-nkz-text-primary">
        {t('zoneDoses.totals', { n: res.totals.n_kg == null ? DASH : formatKgHa(res.totals.n_kg, lang), mean: k1(res.totals.mean_n_kg_ha), uniform: res.totals.uniform_n_kg == null ? DASH : formatKgHa(res.totals.uniform_n_kg, lang) })}
      </p>
      {res.notices.length > 0 && (
        <ul className="list-disc pl-nkz-stack text-nkz-sm text-nkz-warning">
          {res.notices.map((nt, i) => {
            const v = noticeView(nt, lang);
            return <li key={`${nt.code}-${i}`}>{t(v.key, { ...v.params, defaultValue: nt.code })}</li>;
          })}
        </ul>
      )}
    </Stack>
  );
}

/** "Dosis por zonas": shares the N dose of one pass among the saved zones of a parcel. Read-only: stores nothing. */
export function ZoneDosesBlock({ planId, sheet, parcels }: { planId: string; sheet: PlanSheet; parcels: CampaignParcel[] }) {
  const { t, i18n } = useTranslation('fast-navigator');
  const lang = i18n.language;
  const urns = sheet.parcels.map((p) => p.urn);
  const [parcelPick, setParcelPick] = useState<string | null>(null);
  const parcelUrn = parcelPick && urns.includes(parcelPick) ? parcelPick : (urns[0] ?? null);
  const zonings = useLoad((s) => sheetZonings(planId, sheet.key, parcelUrn as string, s), [planId, sheet.key, parcelUrn], parcelUrn != null);
  const [runPick, setRunPick] = useState<string | null>(null);
  const list = zonings.data ?? [];
  const runId = list.find((z) => z.run_id === runPick)?.run_id ?? list[0]?.run_id ?? null;
  const [strategy, setStrategy] = useState<ZoneStrategy>('uniform');
  const [capText, setCapText] = useState('20');
  const [targetText, setTargetText] = useState('');
  const [productName, setProductName] = useState('');
  const [nPctText, setNPctText] = useState('');
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [busy, setBusy] = useState(false);
  const ctrl = useRef<AbortController | null>(null);
  useEffect(() => () => ctrl.current?.abort(), []);

  const built = buildZoneDosesRequest({ parcelUrn, runId, strategy, capText, targetText, productName, nPctText });
  const key = built.ok ? JSON.stringify(built.body) : '';
  const current = answer && answer.key === key ? answer : null;
  const res = current?.data ?? null;
  const n = sheet.result?.n ?? null;

  const calculate = async () => {
    if (!built.ok) return;
    ctrl.current?.abort();
    const c = new AbortController();
    ctrl.current = c;
    setBusy(true);
    try {
      const data = await zoneDoses(planId, sheet.key, built.body, c.signal);
      if (!c.signal.aborted) setAnswer({ key, data, error: null });
    } catch (error) {
      if (!c.signal.aborted) setAnswer({ key, data: null, error });
    } finally {
      if (!c.signal.aborted) setBusy(false);
    }
  };

  const problem = built.ok ? null : built.problem;
  const strategyOptions = STRATEGIES.map((s) => ({ value: s, label: t(`zoneDoses.strategy.${s}`) }));
  const k1 = (v: number | null | undefined) => formatDecimal1(v, lang);

  return (
    <Surface variant="raised" padding="stack">
      <Stack gap="inline">
        <Inline gap="inline" align="center" wrap>
          <h3 className="font-semibold text-nkz-text-primary">{t('zoneDoses.title')}</h3>
          <Badge intent="warning">{t('zoneDoses.experimental')}</Badge>
        </Inline>
        <p className="text-nkz-xs text-nkz-text-muted">{t('zoneDoses.disclaimer')}</p>

        {urns.length > 1 && (
          <FormField label={t('zoneDoses.parcel')}>
            <Select value={parcelUrn ?? ''} options={urns.map((u) => ({ value: u, label: parcelName(u, parcels) }))}
              onValueChange={(v) => { setParcelPick(v); setRunPick(null); }} />
          </FormField>
        )}

        {zonings.error != null && <ErrorBanner error={zonings.error} onRetry={zonings.retry} />}
        {zonings.loading && <p className="text-nkz-sm text-nkz-text-secondary">{t('common.loading')}</p>}
        {!zonings.loading && zonings.error == null && list.length === 0 && (
          <p role="status" className="text-nkz-sm text-nkz-text-secondary">{t('zoneDoses.noZoning')}</p>
        )}

        {list.length > 0 && (
          <Stack gap="inline">
            <FormGrid columns={2}>
              <FormField label={t('zoneDoses.zoningLabel')}>
                <Select value={runId ?? ''} options={list.map((z) => { const l = zoningLabel(z, lang); return { value: z.run_id, label: t(l.key, l.params) }; })}
                  onValueChange={setRunPick} />
              </FormField>
              <FormField label={t('zoneDoses.strategyLabel')}>
                <Select value={strategy} options={strategyOptions} onValueChange={(v) => setStrategy(v as ZoneStrategy)} />
              </FormField>
            </FormGrid>
            <p className="text-nkz-xs text-nkz-text-muted">{t(`zoneDoses.strategyHint.${strategy}`)}</p>

            <FormGrid columns={2}>
              <FormField label={t('zoneDoses.target')} error={problem === 'target' && targetText.trim() !== '' ? t('zoneDoses.problem.target') : undefined}>
                <Input type="number" min={0} step="any" value={targetText} aria-label={t('zoneDoses.target')} onChange={(e) => setTargetText(e.target.value)} />
              </FormField>
              <FormField label={t('zoneDoses.cap')} error={problem === 'cap' ? t('zoneDoses.problem.cap') : undefined}>
                <Inline gap="inline" align="center" wrap>
                  <Input type="number" min={0} max={30} step="any" value={capText} aria-label={t('zoneDoses.cap')} onChange={(e) => setCapText(e.target.value)} />
                  {res && res.cap.min_n_kg_ha != null && res.cap.max_n_kg_ha != null && (
                    <span className="text-nkz-sm text-nkz-text-secondary">
                      {t('zoneDoses.capRange', { min: k1(res.cap.min_n_kg_ha), max: k1(res.cap.max_n_kg_ha) })}
                    </span>
                  )}
                </Inline>
              </FormField>
            </FormGrid>
            <p className="text-nkz-xs text-nkz-text-muted">
              {n ? t('zoneDoses.sheetNeed', { avg: formatKgHa(n.avg_kg_ha, lang), min: formatKgHa(n.min_kg_ha, lang), max: formatKgHa(n.max_kg_ha, lang) }) : t('zoneDoses.sheetNeedMissing')}
            </p>

            <FormGrid columns={2}>
              <FormField label={t('zoneDoses.productName')} error={problem === 'product' ? t('zoneDoses.problem.product') : undefined}>
                <Input value={productName} aria-label={t('zoneDoses.productName')} onChange={(e) => setProductName(e.target.value)} />
              </FormField>
              <FormField label={t('zoneDoses.productRichness')}>
                <Input type="number" min={0} max={100} step="any" value={nPctText} aria-label={t('zoneDoses.productRichness')} onChange={(e) => setNPctText(e.target.value)} />
              </FormField>
            </FormGrid>

            <Inline gap="inline" align="center">
              <Button variant="primary" loading={busy} disabled={!built.ok} onClick={calculate}>{t('zoneDoses.calculate')}</Button>
            </Inline>
          </Stack>
        )}

        {current?.error != null && <ErrorBanner error={current.error} onRetry={calculate} />}

        {res && <ZoneDosesResult res={res} />}
      </Stack>
    </Surface>
  );
}

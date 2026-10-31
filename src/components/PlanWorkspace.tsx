import React, { useEffect, useRef, useState } from 'react';
import { useAuth, useTranslation } from '@nekazari/sdk';
import { Badge, Button, EmptyState, Inline, Skeleton, Stack, Tabs } from '@nekazari/ui-kit';
import { useSearchParams } from 'react-router-dom';
import { calculatePlan, campaignParcels, getPlan } from '../api/fast';
import type { Plan } from '../api/types';
import { useLoad } from '../hooks/useLoad';
import { errorView } from '../model/errors';
import { formatDate, pdfLang } from '../model/format';
import { canEdit, rolesFrom } from '../model/roles';
import { closePlanParams, openSheetParams, readPlanView, type Tab } from '../model/urlState';
import { DataTab } from './DataTab';
import { ErrorBanner } from './ErrorBanner';
import { NeedsTab } from './NeedsTab';
import { PdfButton } from './PdfButton';
import { SheetCard } from './SheetCard';
import { StateBadge } from './StateBadge';
import { Wizard } from './Wizard';

/** One plan: header, sheets on the left, the tabs of the selected sheet on the right. */
/** `initial.calcError` lets a test show the banner of a failed calculation. */
export function PlanWorkspace({ planId, campaign, initial }: { planId: string; campaign: number; initial?: { calcError?: unknown } }) {
  const { t, i18n } = useTranslation('fast-navigator');
  const { hasRole } = useAuth();
  const roles = rolesFrom(hasRole);
  const [params, setParams] = useSearchParams();
  const view = readPlanView(params);

  const loaded = useLoad((s) => getPlan(planId, s), [planId]);
  const [local, setLocal] = useState<Plan | null>(null);
  const last = useRef<Plan | null>(null);
  const [calcError, setCalcError] = useState<unknown>(initial?.calcError ?? null);
  const [calculating, setCalculating] = useState(false);
  const [adding, setAdding] = useState(false);

  // The newest plan we hold: what a save returned, else what was loaded, else the last one shown
  // (so a reload does not blank the form).
  const plan = local ?? loaded.data ?? last.current;
  const parcelsCampaign = plan?.campaign ?? campaign;
  const parcelsLoad = useLoad((s) => campaignParcels(parcelsCampaign, s), [parcelsCampaign], plan != null);
  useEffect(() => { if (loaded.data) setLocal(null); }, [loaded.data]);
  useEffect(() => { last.current = plan; });

  const back = () => setParams(closePlanParams(params));
  const lang = i18n.language;

  if (!plan) {
    if (loaded.error != null) {
      const v = errorView(loaded.error);
      return (
        <Stack gap="inline">
          <ErrorBanner error={loaded.error} onRetry={v.backToList ? undefined : loaded.retry} />
          <div><Button variant="secondary" onClick={back}>{t('workspace.back')}</Button></div>
        </Stack>
      );
    }
    return <Skeleton variant="rect" height={160} />;
  }

  const editable = canEdit(plan.state, roles);
  const sheets = plan.sheets;
  const selectedKey = sheets.some((s) => s.key === view.sheet) ? view.sheet : sheets[0]?.key ?? null;
  const sheet = sheets.find((s) => s.key === selectedKey) ?? null;
  const parcels = parcelsLoad.data?.parcels ?? [];
  const calculated = sheets.length > 0 && sheets.every((s) => s.result !== null);
  const needsCalc = editable && sheets.length > 0 && (!plan.calc_fresh || !calculated);
  const stale = (plan.state === 'draft' || plan.state === 'calculated') && sheets.length > 0 && !plan.calc_fresh;
  const counts = { block: 0, warn: 0, info: 0 };
  for (const f of plan.findings) counts[f.severity] += 1;
  const sig = plan.signature;
  const showWizard = editable && (sheets.length === 0 || adding) && parcelsLoad.data != null;

  const calculate = async () => {
    setCalculating(true); setCalcError(null);
    try { setLocal(await calculatePlan(plan.id, plan.row_version)); } catch (e) { setCalcError(e); } finally { setCalculating(false); }
  };
  const saved = (p: Plan) => { setLocal(p); setAdding(false); setCalcError(null); };

  return (
    <Stack gap="stack">
      <Inline gap="inline" align="center" justify="between" wrap>
        <Inline gap="inline" align="center" wrap>
          <Button size="sm" variant="ghost" onClick={back}>← {t('workspace.back')}</Button>
          <h1 className="text-nkz-xl font-semibold text-nkz-text-primary">{t('workspace.title', { campaign: plan.campaign, version: plan.version })}</h1>
          <StateBadge state={plan.state} />
        </Inline>
        <PdfButton planId={plan.id} lang={pdfLang(lang)} />
      </Inline>

      {sig && (plan.state === 'signed' || plan.state === 'superseded') && (
        <div className="rounded-nkz-md border border-nkz-success bg-nkz-success-soft p-nkz-inline text-nkz-sm text-nkz-text-primary">
          {t(sig.registration_number ? 'workspace.signedByAdvisor' : 'workspace.signedByHolder', {
            name: sig.name, number: sig.registration_number ?? '', date: formatDate(plan.signed_at ?? sig.signed_at, lang),
            hash: (plan.snapshot_sha256 ?? '').slice(0, 12),
          })}
        </div>
      )}
      {plan.state === 'in_review' && !roles.technician && (
        <div className="rounded-nkz-md border border-nkz-warning bg-nkz-warning-soft p-nkz-inline text-nkz-sm text-nkz-text-primary">{t('workspace.inReview')}</div>
      )}
      {stale && (
        <div className="rounded-nkz-md border border-nkz-warning bg-nkz-warning-soft p-nkz-inline text-nkz-sm text-nkz-text-primary">↻ {t('workspace.stale')}</div>
      )}

      <Inline gap="inline" align="center" wrap>
        {counts.block > 0 && <Badge intent="negative">{t('list.block', { count: counts.block })}</Badge>}
        {counts.warn > 0 && <Badge intent="warning">{t('list.warn', { count: counts.warn })}</Badge>}
        {needsCalc && <Button variant="primary" loading={calculating} onClick={calculate}>{t(calculated ? 'workspace.recalculate' : 'workspace.calculate')}</Button>}
        {editable && sheets.length > 0 && !adding && <Button size="sm" variant="secondary" onClick={() => setAdding(true)}>+ {t('workspace.addSheet')}</Button>}
      </Inline>
      {calcError != null && <ErrorBanner error={calcError} onRetry={calculate} planState={plan.state} />}
      {parcelsLoad.error != null && <ErrorBanner error={parcelsLoad.error} onRetry={parcelsLoad.retry} />}

      {showWizard && parcelsLoad.data && <Wizard plan={plan} parcels={parcelsLoad.data} onSaved={saved} onReload={loaded.retry} />}
      {!showWizard && sheets.length === 0 && (
        <EmptyState title={t('workspace.noSheets')} description={editable ? undefined : t('workspace.noSheetsReadOnly')} />
      )}

      {sheets.length > 0 && !adding && sheet && (
        <div className="grid grid-cols-1 gap-nkz-stack md:grid-cols-4">
          <Stack gap="inline">
            {sheets.map((s) => (
              <SheetCard key={s.key} sheet={s} parcels={parcels} selected={s.key === selectedKey}
                onSelect={() => setParams(openSheetParams(params, s.key, view.tab))} />
            ))}
          </Stack>
          <div className="md:col-span-3">
            <Tabs value={view.tab} defaultValue="data" onValueChange={(v) => setParams(openSheetParams(params, sheet.key, v as Tab))}>
              <Tabs.List>
                <Tabs.Trigger value="data">{t('workspace.tabs.data')}</Tabs.Trigger>
                <Tabs.Trigger value="needs">{t('workspace.tabs.needs')}</Tabs.Trigger>
              </Tabs.List>
              <Tabs.Content value="data">
                <DataTab plan={plan} sheet={sheet} parcels={parcels} editable={editable} roles={roles} onSaved={saved} onReload={() => { loaded.retry(); }} />
              </Tabs.Content>
              <Tabs.Content value="needs"><NeedsTab result={sheet.result} /></Tabs.Content>
            </Tabs>
          </div>
        </div>
      )}
    </Stack>
  );
}

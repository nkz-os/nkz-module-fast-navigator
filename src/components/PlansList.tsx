import React, { useState } from 'react';
import { useAuth, useTranslation } from '@nekazari/sdk';
import { Badge, Button, EmptyState, Inline, Select, Skeleton, Stack, Surface } from '@nekazari/ui-kit';
import { useSearchParams } from 'react-router-dom';
import { createPlan, listPlans } from '../api/fast';
import type { PlanListItem } from '../api/types';
import { FastApiError } from '../api/client';
import { useLoad } from '../hooks/useLoad';
import { campaignChoices } from '../model/campaign';
import { formatDate, pdfLang } from '../model/format';
import { rolesFrom } from '../model/roles';
import { campaignParams } from '../model/urlState';
import { ErrorBanner } from './ErrorBanner';
import { PdfButton } from './PdfButton';
import { StateBadge } from './StateBadge';

/** After a 409 on create: the open plan of the campaign (highest version that is not superseded). */
export function afterCreateConflict(list: PlanListItem[], campaign: number): string | null {
  const open = list.filter((p) => p.campaign === campaign && p.state !== 'superseded');
  if (open.length === 0) return null;
  return open.reduce((a, b) => (b.version > a.version ? b : a)).id;
}

export function PlansList({ campaign, onOpen }: { campaign: number; onOpen: (planId: string) => void }) {
  const { t, i18n } = useTranslation('fast-navigator');
  const { hasRole } = useAuth();
  const roles = rolesFrom(hasRole);
  const [params, setParams] = useSearchParams();
  const plans = useLoad((s) => listPlans(campaign, s), [campaign]);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<unknown>(null);
  const lang = i18n.language;

  const create = async () => {
    setCreating(true);
    setCreateError(null);
    try {
      onOpen((await createPlan(campaign)).id);
    } catch (e) {
      if (e instanceof FastApiError && e.status === 409) {
        try {
          const id = afterCreateConflict(await listPlans(campaign), campaign);
          if (id) { onOpen(id); return; }
        } catch (inner) { setCreateError(inner); return; }
      }
      setCreateError(e);
    } finally {
      setCreating(false);
    }
  };

  const options = campaignChoices(campaign, new Date()).map((c) => ({ value: String(c), label: String(c) }));

  return (
    <Stack gap="stack">
      <Inline gap="inline" align="center" justify="between" wrap>
        <h1 className="text-nkz-xl font-semibold text-nkz-text-primary">{t('list.title')}</h1>
        <Inline gap="inline" align="center">
          <span className="text-nkz-sm text-nkz-text-secondary">{t('list.campaign')}</span>
          <Select value={String(campaign)} options={options} size="sm"
            onValueChange={(v) => setParams(campaignParams(params, Number(v)))} />
        </Inline>
      </Inline>

      {plans.loading && <Skeleton variant="rect" height={64} />}
      {!plans.loading && plans.error != null && <ErrorBanner error={plans.error} onRetry={plans.retry} />}
      {createError != null && <ErrorBanner error={createError} />}

      {plans.data && plans.data.length === 0 && (
        <EmptyState title={t('list.empty', { campaign })}
          description={roles.canWrite ? undefined : t('list.createRestricted')}
          action={roles.canWrite ? (
            <Button variant="primary" loading={creating} onClick={create}>{t('list.create', { campaign })}</Button>
          ) : undefined} />
      )}

      {plans.data && plans.data.length > 0 && (
        <Stack gap="inline">
          {plans.data.map((p) => (
            <Surface key={p.id} variant="raised" padding="stack">
              <Inline gap="inline" align="center" justify="between" wrap>
                <Inline gap="inline" align="center" wrap>
                  <span className="font-medium text-nkz-text-primary">{t('list.version', { campaign: p.campaign, version: p.version })}</span>
                  <StateBadge state={p.state} />
                  {p.state === 'signed' && p.signed_at && (
                    <span className="text-nkz-sm text-nkz-text-secondary">{formatDate(p.signed_at, lang)}</span>
                  )}
                  {p.findings.block > 0 && <Badge intent="negative">{t('list.block', { count: p.findings.block })}</Badge>}
                  {p.findings.warn > 0 && <Badge intent="warning">{t('list.warn', { count: p.findings.warn })}</Badge>}
                  {(p.state === 'draft' || p.state === 'calculated') && !p.calc_fresh && (
                    <Badge intent="warning">{t('list.stale')}</Badge>
                  )}
                  <span className="text-nkz-xs text-nkz-text-muted">{t('list.sheets', { count: p.sheets_count })}</span>
                </Inline>
                <Inline gap="inline" align="center">
                  <PdfButton planId={p.id} lang={pdfLang(lang)} />
                  <Button size="sm" variant="primary" onClick={() => onOpen(p.id)}>{t('list.open')}</Button>
                </Inline>
              </Inline>
            </Surface>
          ))}
        </Stack>
      )}
    </Stack>
  );
}

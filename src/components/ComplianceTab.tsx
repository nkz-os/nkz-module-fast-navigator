import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Badge, Button, Inline, Skeleton, Stack, Surface } from '@nekazari/ui-kit';
import { getPlanCompliance } from '../api/fast';
import { useLoad } from '../hooks/useLoad';
import { formatKgHa } from '../model/format';
import { ErrorBanner } from './ErrorBanner';

interface Props {
  planId: string;
  sheetKey: string;
}

const STATUS_INTENT = {
  ok: 'positive',
  at_risk: 'warning',
  exceeded: 'negative',
  incomplete: 'default',
} as const;

export function ComplianceTab({ planId, sheetKey }: Props) {
  const { t, i18n } = useTranslation('fast-navigator');
  const lang = i18n.language;
  const loaded = useLoad((s) => getPlanCompliance(planId, s), [planId]);

  if (loaded.loading && !loaded.data) {
    return <Skeleton variant="rect" height={120} />;
  }
  if (loaded.error != null) {
    return <ErrorBanner error={loaded.error} onRetry={loaded.retry} />;
  }
  const report = loaded.data;
  if (!report) return null;

  const sheet = report.sheets.find((s) => s.key === sheetKey) ?? null;
  const fmt = (v: number | null | undefined) => (v == null ? '—' : `${formatKgHa(v, lang)} ${t('common.unit.kgHa')}`);

  return (
    <Stack gap="stack">
      <Surface variant="raised" padding="stack">
        <Stack gap="inline">
          <Inline gap="inline" align="center" justify="between" wrap>
            <Inline gap="inline" align="center" wrap>
              <h3 className="font-semibold text-nkz-text-primary">{t('compliance.title')}</h3>
              {sheet && <Badge intent={STATUS_INTENT[sheet.status]}>{sheet.status}</Badge>}
              <span className="text-nkz-xs text-nkz-text-muted">
                {report.window.from} → {report.window.until}
              </span>
            </Inline>
            <Button size="sm" variant="ghost" onClick={loaded.retry}>{t('compliance.refresh')}</Button>
          </Inline>

          {sheet ? (
            <Stack gap="tight">
              {(
                [
                  ['mineral_n_kg_ha', t('compliance.mineralN')],
                  ['organic_n_total_kg_ha', t('compliance.organicN')],
                  ['p2o5_kg_ha', 'P₂O₅'],
                  ['k2o_kg_ha', 'K₂O'],
                ] as const
              ).map(([key, label]) => (
                <Inline key={key} gap="inline" align="center" wrap>
                  <span className="w-24 text-nkz-sm font-medium text-nkz-text-primary">{label}</span>
                  <span className="text-nkz-xs text-nkz-text-secondary">
                    {t('compliance.planned')}: <strong>{fmt(sheet.planned[key])}</strong>
                  </span>
                  <span className="text-nkz-xs text-nkz-text-secondary">
                    {t('compliance.realized')}: <strong>{fmt(sheet.realized[key])}</strong>
                  </span>
                  {sheet.difference[key] != null && (
                    <Badge intent={sheet.difference[key]! > 0 ? 'warning' : 'default'}>
                      Δ {fmt(sheet.difference[key])}
                    </Badge>
                  )}
                </Inline>
              ))}
            </Stack>
          ) : (
            <p className="text-nkz-sm text-nkz-text-secondary">{t('compliance.noOps')}</p>
          )}
        </Stack>
      </Surface>

      {sheet && (
        <Surface variant="raised" padding="stack">
          <Stack gap="inline">
            <h4 className="font-semibold text-nkz-text-primary">{t('compliance.opsTitle')}</h4>
            {sheet.applications.length === 0 ? (
              <p className="text-nkz-sm text-nkz-text-secondary">{t('compliance.noOps')}</p>
            ) : (
              sheet.applications.map((op, i) => (
                <Surface key={op.operation || i} variant="sunken" padding="inline">
                  <Inline gap="inline" align="center" justify="between" wrap>
                    <Stack gap="tight">
                      <Inline gap="tight" align="center" wrap>
                        <strong className="text-nkz-sm text-nkz-text-primary">{op.product || '—'}</strong>
                        <span className="text-nkz-xs text-nkz-text-muted">{op.date || '—'}</span>
                        {op.organic && <Badge intent="info">Org.</Badge>}
                        <Badge intent="default">{op.status}</Badge>
                      </Inline>
                      <span className="text-nkz-xs text-nkz-text-secondary">
                        N {fmt(op.n_kg_ha)} · P₂O₅ {fmt(op.p2o5_kg_ha)} · K₂O {fmt(op.k2o_kg_ha)}
                      </span>
                    </Stack>
                  </Inline>
                </Surface>
              ))
            )}
          </Stack>
        </Surface>
      )}

      {report.unattributed.length > 0 && (
        <Surface variant="raised" padding="stack">
          <Stack gap="tight">
            <h4 className="font-semibold text-nkz-warning">{t('compliance.unattributedTitle')}</h4>
            {report.unattributed.map((u, i) => (
              <p key={i} className="text-nkz-xs text-nkz-text-secondary">
                {u.date || '—'} · {u.parcel.split(':').pop()} ({u.reason})
              </p>
            ))}
          </Stack>
        </Surface>
      )}
    </Stack>
  );
}

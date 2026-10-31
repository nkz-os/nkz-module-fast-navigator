import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Badge, Inline, Stack, Surface } from '@nekazari/ui-kit';
import type { NResult, OxideResult, SheetResult, Sourced } from '../api/types';
import { formatDecimal2, formatKgHa, formatMgKg, formatSignedKgHa } from '../model/format';
import { bandScale, nBreakdown, oxideView } from '../model/needs';
import { ProvenanceChip } from './ProvenanceChip';

const groupsOf = (r: SheetResult) => [...new Set(r.missing.map((m) => m.field.split('.')[0]))];

function Missing({ result }: { result: SheetResult }) {
  const { t } = useTranslation('fast-navigator');
  return <>{groupsOf(result).map((g) => t(`missing.${g}`, { defaultValue: g })).join(', ')}</>;
}

function NBand({ n }: { n: NResult }) {
  const { t, i18n } = useTranslation('fast-navigator');
  const lang = i18n.language;
  const { pct } = bandScale(n);
  const k = (v: number) => formatKgHa(v, lang);
  return (
    <Stack gap="tight">
      <p className="text-nkz-base text-nkz-text-primary">
        <span>{t('needs.min')} <strong>{k(n.min_kg_ha)}</strong></span>{' · '}
        <span>{t('needs.avg')} <strong>{k(n.avg_kg_ha)}</strong></span>{' · '}
        <span>{t('needs.max')} <strong>{k(n.max_kg_ha)}</strong></span>{' '}
        <span className="text-nkz-sm text-nkz-text-secondary">{t('common.unit.kgHa')}</span>
      </p>
      <div className="relative h-6 rounded-nkz-sm bg-nkz-surface-sunken" role="img"
        aria-label={t('needs.bandLabel', { min: k(n.min_kg_ha), avg: k(n.avg_kg_ha), max: k(n.max_kg_ha) })}>
        <div className="absolute top-0 h-6 rounded-nkz-sm bg-nkz-accent-soft"
          style={{ left: `${pct(n.before_credits.min_kg_ha)}%`, width: `${pct(n.before_credits.max_kg_ha) - pct(n.before_credits.min_kg_ha)}%` }} />
        <div className="absolute top-1 h-4 rounded-nkz-sm bg-nkz-accent-base"
          style={{ left: `${pct(n.min_kg_ha)}%`, width: `${pct(n.max_kg_ha) - pct(n.min_kg_ha)}%` }} />
        {n.levels_kg_ha.map((v, i) => (
          <div key={i} className="absolute top-0 h-6 w-px bg-nkz-text-primary" style={{ left: `${pct(v)}%` }}
            aria-label={t('needs.level', { i: i + 1, v: k(v) })} />
        ))}
        <div className="absolute top-0 h-6 w-1 bg-nkz-text-primary" style={{ left: `${pct(n.avg_kg_ha)}%` }} />
      </div>
      <p className="text-nkz-xs text-nkz-text-muted">
        {t('needs.beforeCredits')}: {k(n.before_credits.min_kg_ha)}–{k(n.before_credits.max_kg_ha)} {t('common.unit.kgHa')}
      </p>
    </Stack>
  );
}

function Breakdown({ result }: { result: SheetResult }) {
  const { t, i18n } = useTranslation('fast-navigator');
  const lang = i18n.language;
  return (
    <Stack gap="tight">
      <h4 className="font-medium text-nkz-text-primary">{t('needs.breakdown')}</h4>
      {nBreakdown(result).map((row) => (
        <Inline key={row.term} gap="inline" align="center" wrap>
          <span className="w-64 text-nkz-sm text-nkz-text-secondary">
            {row.kind === 'credit' ? '− ' : row.kind === 'term' ? '+ ' : ''}{t(`needs.term.${row.term}`)}
          </span>
          <span className="w-24 text-right text-nkz-sm font-medium text-nkz-text-primary">
            {row.kind === 'divisor' ? `÷ ${formatDecimal2(row.value, lang)}`
              : row.kind === 'credit' ? `−${formatKgHa(row.value, lang)}` : formatSignedKgHa(row.value, lang)}
          </span>
          {row.citation && <Badge intent="default">▤ {row.citation}</Badge>}
          {row.chips.map((c: Sourced, i) => <ProvenanceChip key={i} value={c} />)}
        </Inline>
      ))}
    </Stack>
  );
}

function Oxide({ label, o, soilKey, result }: { label: string; o: OxideResult | null; soilKey: string; result: SheetResult }) {
  const { t, i18n } = useTranslation('fast-navigator');
  const lang = i18n.language;
  if (!o) {
    return <p className="text-nkz-sm text-nkz-warning">{t('needs.oxideMissing', { oxide: label })} <Missing result={result} /></p>;
  }
  const v = oxideView(o);
  const soil = result.inputs[soilKey] as Sourced<number> | undefined;
  const soilValue = soil && typeof soil.value === 'number' ? soil.value : null;
  const top = Math.max(o.high_from_mg_kg ?? 0, o.threshold_mg_kg ?? 0, soilValue ?? 0) * 1.25 || 1;
  const pct = (x: number) => Math.min(100, (x / top) * 100);
  const k = (x: number) => formatKgHa(x, lang);
  return (
    <Stack gap="tight">
      <p className="font-medium text-nkz-text-primary">
        {label} <span className="text-nkz-sm text-nkz-text-secondary">({t('common.unit.kgHa')})</span>{' '}
        <strong>{k(o.rate_kg_ha)}</strong>
        {v.soilClassKey && <> · <Badge intent="info">{t('needs.soilClass', { class: t(v.soilClassKey) })}</Badge></>}
      </p>
      {v.soilClassKey ? (
        <div>
          <div className="relative h-3 rounded-nkz-sm bg-nkz-surface-sunken" role="img"
            aria-label={t('needs.soilBar', { value: soilValue == null ? '—' : formatMgKg(soilValue, lang), threshold: v.thresholdText ?? '—', high: v.highFromText ?? '—' })}>
            {soilValue != null && <div className="absolute h-3 rounded-nkz-sm bg-nkz-accent-base" style={{ width: `${pct(soilValue)}%` }} />}
            {o.threshold_mg_kg != null && <div className="absolute h-3 w-px bg-nkz-text-primary" style={{ left: `${pct(o.threshold_mg_kg)}%` }} />}
            {o.high_from_mg_kg != null && <div className="absolute h-3 w-px bg-nkz-text-primary" style={{ left: `${pct(o.high_from_mg_kg)}%` }} />}
          </div>
          <p className="text-nkz-xs text-nkz-text-muted">
            {t('needs.soilNow', { value: soilValue == null ? '—' : formatMgKg(soilValue, lang) })}
            {' · '}{t('needs.thresholds', { low: v.thresholdText ?? '—', high: v.highFromText ?? '—' })}
            {' → '}{t(v.basisKey)}
          </p>
        </div>
      ) : (
        <p className="text-nkz-xs text-nkz-text-muted">{t('needs.strategy4')} → {t(v.basisKey)}</p>
      )}
      <p className="text-nkz-sm text-nkz-text-secondary">
        {t('needs.doseIs')}{' '}
        {o.basis === 'half_export' ? <>{t('basis.half_export')} {k(o.before_organic_kg_ha)}</> : null}
        {o.basis === 'buildup' ? <>{t('needs.component.buildup')} {k(o.before_organic_kg_ha)}</> : null}
        {o.basis === 'export' ? <>{t('needs.component.export')} {k(o.before_organic_kg_ha)}</> : null}
        {o.basis === 'buildup_and_export' ? <>{t('needs.component.export')} {k(o.exported_kg_ha)} + {t('needs.component.buildup')} {k(o.buildup_per_year_kg_ha)}</> : null}
        {o.basis === 'none' ? <>{t('basis.none')} {k(o.before_organic_kg_ha)}</> : null}
        {' − '}{t('needs.organicCredit')} {k(o.organic_credit_kg_ha)} = <strong>{k(o.rate_kg_ha)}</strong> {t('common.unit.kgHa')}
      </p>
    </Stack>
  );
}

/** The needs of a sheet: the N band, its breakdown, and P2O5 / K2O with the class the engine decided. */
export function NeedsTab({ result }: { result: SheetResult | null }) {
  const { t } = useTranslation('fast-navigator');
  if (!result) return <p className="text-nkz-sm text-nkz-text-secondary">{t('data.notCalculated')}</p>;
  const v = result.versions;
  return (
    <Stack gap="stack">
      {result.provisional && <Badge intent="warning">{t('sheet.provisional')}</Badge>}
      <Surface variant="raised" padding="stack">
        <Stack gap="inline">
          <h3 className="font-semibold text-nkz-text-primary">{t('needs.nTitle')}</h3>
          {result.n ? (
            <>
              <NBand n={result.n} />
              <Breakdown result={result} />
            </>
          ) : (
            <div role="status" className="rounded-nkz-md border border-dashed border-nkz-warning p-nkz-inline text-nkz-sm text-nkz-warning">
              {t('needs.nMissing')} <Missing result={result} />
            </div>
          )}
        </Stack>
      </Surface>
      <Surface variant="raised" padding="stack">
        <Stack gap="inline">
          <Oxide label={t('needs.p2o5')} o={result.p2o5} soilKey="soil.p_olsen_mg_kg" result={result} />
          <Oxide label={t('needs.k2o')} o={result.k2o} soilKey="soil.k_mg_kg" result={result} />
        </Stack>
      </Surface>
      <p className="text-nkz-xs text-nkz-text-muted">
        {t('needs.versions', { engine: v.engine ?? '—', calc: v.calc ?? '—' })}
        {v.coefficients ? ` · ${t('needs.coefficientsVersion', { v: v.coefficients })}` : ''}
      </p>
    </Stack>
  );
}

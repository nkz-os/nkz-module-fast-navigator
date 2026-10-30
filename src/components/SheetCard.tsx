import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Badge, Inline, Stack } from '@nekazari/ui-kit';
import type { CampaignParcel, PlanSheet } from '../api/types';
import { formatHa, formatKgHa } from '../model/format';
import { sheetArea } from '../model/sheets';
import { CropLabel } from './CropLabel';

/** Scale of the mini band: the largest figure rounded up to 50, so bands of different sheets compare. */
function bandMax(n: NonNullable<NonNullable<PlanSheet['result']>['n']>): number {
  return Math.max(50, Math.ceil(Math.max(n.max_kg_ha, n.before_credits.max_kg_ha) / 50) * 50);
}

/** One sheet in the list: crop, hectares, a small N band, what is missing and whether it is provisional. */
export function SheetCard({ sheet, parcels, selected, onSelect }: {
  sheet: PlanSheet; parcels: CampaignParcel[]; selected: boolean; onSelect: () => void;
}) {
  const { t, i18n } = useTranslation('fast-navigator');
  const result = sheet.result;
  const area = sheetArea(result, parcels, sheet.parcels.map((p) => p.urn));
  const crop = (result?.inputs['crop.eppo'] as { value?: string | null } | undefined)?.value ?? sheet.inputs.crop_eppo;
  const n = result?.n ?? null;
  const max = n ? bandMax(n) : 1;
  return (
    <button type="button" onClick={onSelect} aria-current={selected ? 'true' : undefined}
      className={`w-full text-left rounded-nkz-md border p-nkz-inline ${selected ? 'border-nkz-accent-base bg-nkz-accent-soft' : 'border-nkz-border bg-nkz-surface'}`}>
      <Stack gap="tight">
        <Inline gap="inline" justify="between" align="center">
          <span className="font-medium text-nkz-text-primary"><CropLabel eppo={crop} /></span>
          <span className="text-nkz-xs text-nkz-text-secondary">{area == null ? '—' : formatHa(area, i18n.language)} {t('common.unit.ha')}</span>
        </Inline>
        {n ? (
          <div aria-label={t('sheet.nBand', { min: formatKgHa(n.min_kg_ha, i18n.language), avg: formatKgHa(n.avg_kg_ha, i18n.language), max: formatKgHa(n.max_kg_ha, i18n.language) })}>
            <div className="relative h-2 rounded-nkz-sm bg-nkz-surface-sunken">
              <div className="absolute h-2 rounded-nkz-sm bg-nkz-accent-base"
                style={{ left: `${(n.min_kg_ha / max) * 100}%`, width: `${((n.max_kg_ha - n.min_kg_ha) / max) * 100}%` }} />
            </div>
            <span className="text-nkz-xs text-nkz-text-muted">N {formatKgHa(n.min_kg_ha, i18n.language)}–{formatKgHa(n.max_kg_ha, i18n.language)} {t('common.unit.kgHa')}</span>
          </div>
        ) : (
          <span className="text-nkz-xs text-nkz-text-muted">{t('sheet.nMissing')}</span>
        )}
        <Inline gap="tight" wrap>
          {result && result.missing.length > 0 && <Badge intent="negative">✕ {result.missing.length}</Badge>}
          {result?.provisional && <Badge intent="warning">{t('sheet.provisional')}</Badge>}
        </Inline>
      </Stack>
    </button>
  );
}

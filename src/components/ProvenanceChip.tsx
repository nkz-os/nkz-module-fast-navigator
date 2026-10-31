import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Badge } from '@nekazari/ui-kit';
import type { CycleView, Sourced } from '../api/types';
import { DASH } from '../model/format';
import { chipFor } from '../model/provenance';

/** Symbol + word + colour: the colour never carries the meaning alone. */
export function ProvenanceChip({ value, cycle }: { value: Sourced | null | undefined; cycle?: CycleView | null }) {
  const { t } = useTranslation('fast-navigator');
  const chip = chipFor(value, cycle);
  const tip = t(chip.tooltip.key, chip.tooltip.params);
  return (
    <span title={tip}>
      <Badge intent={chip.intent}>{chip.symbol} {t(chip.key)}</Badge>
    </span>
  );
}

/** A value with its chip. A missing value is "—", never 0. */
export function SourcedValue({ value, format, unit, cycle }: {
  value: Sourced | null | undefined;
  format: (v: number | string) => string;
  unit?: string;
  cycle?: CycleView | null;
}) {
  const known = value != null && value.value != null && value.provenance !== 'missing';
  return (
    <span className="inline-flex items-center gap-2">
      <span className="text-nkz-text-primary">{known ? `${format(value!.value as number | string)}${unit ? ` ${unit}` : ''}` : DASH}</span>
      <ProvenanceChip value={value} cycle={cycle} />
    </span>
  );
}

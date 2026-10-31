import React, { useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Button, FormField, Inline, Input } from '@nekazari/ui-kit';
import { nextDeclarableYear, yearProblem } from '../model/declaredYears';

interface Props {
  campaign: number;
  declared: Record<string, number>;
  onAdd: (year: number, kg: number) => void;
  /** Test hook: start with these values instead of the proposal. */
  initial?: { year?: string; kg?: string };
}

/** Add one declared year: nothing is added to the sheet until year and yield are valid. */
export function DeclareYearForm({ campaign, declared, onAdd, initial }: Props) {
  const { t } = useTranslation('fast-navigator');
  const [open, setOpen] = useState(initial !== undefined);
  const [year, setYear] = useState(initial?.year ?? String(nextDeclarableYear(campaign, declared)));
  const [kg, setKg] = useState(initial?.kg ?? '');
  if (!open) {
    return <Button size="sm" variant="ghost" onClick={() => { setYear(String(nextDeclarableYear(campaign, declared))); setKg(''); setOpen(true); }}>{t('data.addYear')}</Button>;
  }
  const n = kg.trim() === '' ? null : Number(kg);
  const problem = yearProblem(campaign, declared, Number(year), n);
  const submit = () => { if (problem === null && n !== null) { onAdd(Number(year), n); setOpen(false); } };
  return (
    <Inline gap="inline" align="center" wrap>
      <FormField label={t('data.declareYear.year')} error={problem === 'duplicate' || problem === 'future' || problem === 'year' ? t(`data.declareYear.problem.${problem}`) : undefined}>
        <Input type="number" value={year} min={2000} max={campaign - 1} step={1} onChange={(e) => setYear(e.target.value)} />
      </FormField>
      <FormField label={t('data.declareYear.yield')}>
        <Input type="number" value={kg} min={1} step="any" placeholder={t('data.yieldUnit')} onChange={(e) => setKg(e.target.value)} />
      </FormField>
      <Button size="sm" variant="primary" disabled={problem !== null} onClick={submit}>{t('data.declareYear.add')}</Button>
      <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>{t('common.close')}</Button>
    </Inline>
  );
}

import React, { useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Button, Inline, Input, Stack } from '@nekazari/ui-kit';
import type { SourceCrop } from '../model/crops';
import { cropDisplayName, filterCrops, FALLOW, hasCoefficients } from '../model/crops';
import { EPPO_RE } from '../model/sheets';
import { CropLabel } from './CropLabel';

interface Props {
  /** The crops to choose from; null while loading or when the list could not be had. */
  crops: SourceCrop[] | null;
  loading: boolean;
  failed: boolean;
  value: string | null;
  onChange: (value: string | null) => void;
  /** A fallow is offered first, in one click (previous crop only). */
  allowFallow?: boolean;
  ariaLabel: string;
}

/** Choose a crop by its name in the user's language: type a few letters, click the match. */
export function CropPicker({ crops, loading, failed, value, onChange, allowFallow = false, ariaLabel }: Props) {
  const { t, i18n } = useTranslation('fast-navigator');
  const lang = i18n.language;
  const [query, setQuery] = useState('');
  const [changing, setChanging] = useState(false);

  if (failed || (!loading && crops === null)) {
    // The list is down: the code can still be typed, and the screen says so.
    return (
      <Stack gap="tight">
        <p role="alert" className="text-nkz-sm text-nkz-warning">{t('cropPicker.listFailed')}</p>
        <Input aria-label={ariaLabel} value={value ?? ''}
          onChange={(e) => {
            const v = e.target.value.trim();
            onChange(v.toLowerCase() === FALLOW && allowFallow ? FALLOW : (v.toUpperCase() || null));
          }} />
      </Stack>
    );
  }

  const list = crops ?? [];
  const noCoeffs = value != null && value !== FALLOW && crops !== null && !hasCoefficients(list, value);
  if (value != null && !changing) {
    const known = list.find((c) => c.eppo === value);
    return (
      <Stack gap="tight">
        <Inline gap="inline" align="center" wrap>
          <span className="text-nkz-sm font-medium text-nkz-text-primary">
            {value === FALLOW ? t('cropPicker.fallow') : known ? cropDisplayName(known, lang) : <CropLabel eppo={value} />}
          </span>
          {noCoeffs && <span className="text-nkz-xs text-nkz-warning">⚠ {t('cropPicker.noCoefficients')}</span>}
          <Button size="sm" variant="ghost" onClick={() => { setChanging(true); setQuery(''); }}>{t('cropPicker.change')}</Button>
          <Button size="sm" variant="ghost" onClick={() => onChange(null)}>{t('cropPicker.clear')}</Button>
        </Inline>
        {noCoeffs && <p className="text-nkz-xs text-nkz-text-muted">{t('cropPicker.noCoefficientsHint')}</p>}
      </Stack>
    );
  }

  const matches = filterCrops(list, query, lang);
  const pick = (v: string) => { onChange(v); setChanging(false); setQuery(''); };
  const showFallow = allowFallow && (query.trim() === '' || t('cropPicker.fallow').toLowerCase().startsWith(query.trim().toLowerCase()));
  const typedCode = query.trim().toUpperCase();
  return (
    <Stack gap="tight">
      <Input aria-label={ariaLabel} value={query} placeholder={loading ? t('common.loading') : t('cropPicker.search')}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key !== 'Enter') return;
          e.preventDefault();
          if (query.trim() === '') return;
          if (matches[0]) pick(matches[0].eppo);
        }} />
      <Inline gap="tight" wrap>
        {showFallow && <Button size="sm" variant="secondary" onClick={() => pick(FALLOW)}>{t('cropPicker.fallow')}</Button>}
        {matches.map((c) => (
          <Button key={c.eppo} size="sm" variant="secondary" onClick={() => pick(c.eppo)}>
            {cropDisplayName(c, lang)}{c.has_coefficients ? '' : ` · ${t('cropPicker.noCoefficients')}`}
          </Button>
        ))}
      </Inline>
      {!loading && matches.length === 0 && !showFallow && (
        <Inline gap="inline" align="center" wrap>
          <span className="text-nkz-sm text-nkz-text-secondary">{t('cropPicker.noMatch')}</span>
          {EPPO_RE.test(typedCode) && <Button size="sm" variant="ghost" onClick={() => pick(typedCode)}>{t('cropPicker.useCode', { code: typedCode })}</Button>}
        </Inline>
      )}
      {query.trim() === '' && list.length > matches.length && <p className="text-nkz-xs text-nkz-text-muted">{t('cropPicker.typeToSearch', { count: list.length })}</p>}
      {changing && <Button size="sm" variant="ghost" onClick={() => setChanging(false)}>{t('common.close')}</Button>}
    </Stack>
  );
}

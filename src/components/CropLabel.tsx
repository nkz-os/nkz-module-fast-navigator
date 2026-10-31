import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import { cropName } from '../api/fast';
import { useLoad } from '../hooks/useLoad';
import { EPPO_RE } from '../model/sheets';

/** Name of a crop from its EPPO code; the code itself when the name cannot be had. */
export function CropLabel({ eppo }: { eppo: string | null | undefined }) {
  const { i18n } = useTranslation('fast-navigator');
  const code = eppo ?? '';
  const name = useLoad((s) => cropName(code, i18n.language, s), [code, i18n.language], EPPO_RE.test(code));
  if (!eppo) return <span>—</span>;
  return <span>{name.data ?? eppo}</span>;
}

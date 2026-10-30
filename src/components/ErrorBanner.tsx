import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Button } from '@nekazari/ui-kit';
import type { PlanState } from '../api/types';
import { errorView } from '../model/errors';

/** A failure in words: what happened, which source, and (when known) that the plan did not change. */
export function ErrorBanner({ error, onRetry, planState }: { error: unknown; onRetry?: () => void; planState?: PlanState }) {
  const { t } = useTranslation('fast-navigator');
  const view = errorView(error);
  const params: Record<string, string> = { ...view.params };
  if (params.source) params.source = t(params.source, { defaultValue: params.source.replace(/^source\./, '') });
  const sourceDown = view.key === 'error.sourceUnavailable';
  return (
    <div role="alert" className="rounded-nkz-md border border-nkz-danger bg-nkz-danger-soft p-nkz-inline text-nkz-sm text-nkz-danger">
      <p>
        {t(view.key, params)}
        {sourceDown && planState ? ` ${t('error.planStays', { state: t(`state.${planState}`) })}` : ''}
      </p>
      {view.rules && view.rules.length > 0 && <p>{t('error.rules', { rules: view.rules.join(', ') })}</p>}
      {onRetry && (
        <div className="mt-nkz-tight">
          <Button size="sm" variant="secondary" onClick={onRetry}>{t('common.retry')}</Button>
        </div>
      )}
    </div>
  );
}

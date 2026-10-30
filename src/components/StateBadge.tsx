import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Badge } from '@nekazari/ui-kit';
import type { PlanState } from '../api/types';
import type { BadgeIntent } from '../model/provenance';

const INTENT: Record<PlanState, BadgeIntent> = {
  draft: 'default', calculated: 'info', in_review: 'warning', signed: 'positive', superseded: 'default',
};

export function StateBadge({ state }: { state: PlanState }) {
  const { t } = useTranslation('fast-navigator');
  const label = t(`state.${state}`);
  return <Badge intent={INTENT[state]}>{state === 'superseded' ? <span className="line-through">{label}</span> : label}</Badge>;
}

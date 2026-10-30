import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import { EmptyState } from '@nekazari/ui-kit';
import { useSearchParams } from 'react-router-dom';
import { resolveCampaign } from '../model/campaign';
import { openPlanParams, readPlanView } from '../model/urlState';
import { ModuleFooter } from './ModuleFooter';
import { PlansList } from './PlansList';

/** The whole page: the plan list, or one plan, chosen by the URL. */
export function FastApp() {
  const { t } = useTranslation('fast-navigator');
  const [params, setParams] = useSearchParams();
  const view = readPlanView(params);
  const campaign = resolveCampaign(view.campaign, new Date());
  return (
    <div className="w-full p-nkz-section">
      {view.plan === null
        ? <PlansList campaign={campaign} onOpen={(id) => setParams(openPlanParams(params, id, campaign))} />
        : <EmptyState title={t('app.title')} />}
      <ModuleFooter />
    </div>
  );
}

import React from 'react';
import { useSearchParams } from 'react-router-dom';
import { resolveCampaign } from '../model/campaign';
import { openPlanParams, readPlanView } from '../model/urlState';
import { ModuleFooter } from './ModuleFooter';
import { PlanWorkspace } from './PlanWorkspace';
import { PlansList } from './PlansList';

/** The whole page: the plan list, or one plan, chosen by the URL. */
export function FastApp() {
  const [params, setParams] = useSearchParams();
  const view = readPlanView(params);
  const campaign = resolveCampaign(view.campaign, new Date());
  return (
    <div className="w-full p-nkz-section">
      {view.plan === null
        ? <PlansList campaign={campaign} onOpen={(id) => setParams(openPlanParams(params, id, campaign))} />
        : <PlanWorkspace planId={view.plan} campaign={campaign} />}
      <ModuleFooter />
    </div>
  );
}

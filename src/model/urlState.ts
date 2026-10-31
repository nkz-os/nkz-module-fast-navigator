/** What the page shows lives in the URL (`?campaign=&plan=&sheet=&tab=`), so links and reloads work. */
export type Tab = 'data' | 'needs';

export interface PlanView { campaign: number | null; plan: string | null; sheet: string | null; tab: Tab }

export function readPlanView(p: URLSearchParams): PlanView {
  const c = Number(p.get('campaign'));
  return {
    campaign: Number.isInteger(c) && c >= 2000 && c <= 2100 ? c : null,
    plan: p.get('plan') || null,
    sheet: p.get('sheet') || null,
    tab: p.get('tab') === 'needs' ? 'needs' : 'data',
  };
}

export function campaignParams(cur: URLSearchParams, campaign: number): URLSearchParams {
  const next = new URLSearchParams(cur);
  next.set('campaign', String(campaign));
  next.delete('plan'); next.delete('sheet'); next.delete('tab');
  return next;
}

export function openPlanParams(cur: URLSearchParams, planId: string, campaign: number): URLSearchParams {
  const next = new URLSearchParams(cur);
  next.set('campaign', String(campaign));
  next.set('plan', planId);
  next.delete('sheet'); next.delete('tab');
  return next;
}

export function openSheetParams(cur: URLSearchParams, key: string, tab: Tab): URLSearchParams {
  const next = new URLSearchParams(cur);
  next.set('sheet', key);
  next.set('tab', tab);
  return next;
}

export function closePlanParams(cur: URLSearchParams): URLSearchParams {
  const next = new URLSearchParams(cur);
  next.delete('plan'); next.delete('sheet'); next.delete('tab');
  return next;
}

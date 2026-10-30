import { describe, expect, it } from 'vitest';
import { closePlanParams, openPlanParams, openSheetParams, readPlanView } from './urlState';

const p = (s: string) => new URLSearchParams(s);

describe('url state', () => {
  it('reads the view, falling back to the data tab', () => {
    expect(readPlanView(p('campaign=2027&plan=x&sheet=k&tab=calendar'))).toEqual({ campaign: 2027, plan: 'x', sheet: 'k', tab: 'data' });
    expect(readPlanView(p('tab=needs')).tab).toBe('needs');
    expect(readPlanView(p('campaign=abc')).campaign).toBeNull();
  });
  it('opening a plan keeps foreign keys', () => {
    const n = openPlanParams(p('foo=1&sheet=old'), 'abc', 2027);
    expect([n.get('foo'), n.get('plan'), n.get('campaign'), n.get('sheet')]).toEqual(['1', 'abc', '2027', null]);
  });
  it('opening a sheet sets sheet and tab', () => {
    const n = openSheetParams(p('plan=x'), 'k', 'needs');
    expect([n.get('plan'), n.get('sheet'), n.get('tab')]).toEqual(['x', 'k', 'needs']);
  });
  it('closing a plan leaves the campaign', () => {
    const n = closePlanParams(p('campaign=2027&plan=x&sheet=k&tab=needs&foo=1'));
    expect(n.toString()).toBe('campaign=2027&foo=1');
  });
});

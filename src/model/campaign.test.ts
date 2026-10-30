import { expect, it } from 'vitest';
import { currentCampaign } from './campaign';

it('the agricultural year starts on 1 September', () => {
  expect(currentCampaign(new Date(2026, 7, 31))).toBe(2026);
  expect(currentCampaign(new Date(2026, 8, 1))).toBe(2027);
  expect(currentCampaign(new Date(2027, 0, 15))).toBe(2027);
});

import { campaignChoices, resolveCampaign } from './campaign';

it('the URL campaign wins over the current one', () => {
  expect(resolveCampaign(2026, new Date(2026, 9, 30))).toBe(2026);
  expect(resolveCampaign(null, new Date(2026, 9, 30))).toBe(2027);
});
it('the selector always offers the shown campaign', () => {
  expect(campaignChoices(2030, new Date(2026, 9, 30))).toContain(2030);
  expect(campaignChoices(2027, new Date(2026, 9, 30))).toEqual([2028, 2027, 2026, 2025, 2024]);
});

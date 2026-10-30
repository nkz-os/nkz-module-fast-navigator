import { expect, it } from 'vitest';
import { currentCampaign } from './campaign';

it('the agricultural year starts on 1 September', () => {
  expect(currentCampaign(new Date(2026, 7, 31))).toBe(2026);
  expect(currentCampaign(new Date(2026, 8, 1))).toBe(2027);
  expect(currentCampaign(new Date(2027, 0, 15))).toBe(2027);
});

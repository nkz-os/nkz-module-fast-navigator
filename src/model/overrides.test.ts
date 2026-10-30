import { describe, expect, it } from 'vitest';
import { mayAdjust, overrideRange } from './overrides';

const farmer = { canWrite: true, technician: false };
const tech = { canWrite: true, technician: true };

describe('adjusting a value', () => {
  it('the farmer adjusts only the availability of organic inputs', () => {
    expect(mayAdjust('organic.0.availability', farmer)).toBe(true);
    expect(mayAdjust('soil.ph', farmer)).toBe(false);
    expect(mayAdjust('yield.kg_ha', farmer)).toBe(false);
  });
  it('the technician adjusts what has a range', () => {
    expect(mayAdjust('soil.ph', tech)).toBe(true);
    expect(mayAdjust('irrigation.uptake', tech)).toBe(true);
    expect(mayAdjust('soil.mineral_n_kg_ha', tech)).toBe(false);
  });
  it('shows the allowed range', () => {
    expect(overrideRange('organic.2.availability')).toEqual([0, 1]);
    expect(overrideRange('soil.ph')).toEqual([0, 14]);
    expect(overrideRange('region.nuts')).toBeNull();
  });
});

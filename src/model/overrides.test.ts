import { describe, expect, it } from 'vitest';
import { mayAdjust, overrideRange } from './overrides';

import { rolesFrom } from './roles';

const holder = rolesFrom((r) => r === 'TenantAdmin');
const field = rolesFrom((r) => r === 'Farmer');
const tech = rolesFrom((r) => r === 'TechnicalConsultant');

describe('adjusting a value', () => {
  it('the holder adjusts only the availability of organic inputs', () => {
    expect(mayAdjust('organic.0.availability', holder)).toBe(true);
    expect(mayAdjust('soil.ph', holder)).toBe(false);
    expect(mayAdjust('yield.kg_ha', holder)).toBe(false);
  });
  it('the field worker adjusts nothing', () => {
    expect(mayAdjust('organic.0.availability', field)).toBe(false);
    expect(mayAdjust('soil.ph', field)).toBe(false);
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

import { describe, expect, it } from 'vitest';
import type { PlanState } from '../api/types';
import { canEdit, rolesFrom } from './roles';

const as = (...roles: string[]) => rolesFrom((r) => roles.includes(r));
const STATES: PlanState[] = ['draft', 'calculated', 'in_review', 'signed', 'superseded'];

describe('canEdit', () => {
  it.each([
    ['farmer', as('Farmer'), [true, true, false, false, false]],
    ['technician', as('TechnicalConsultant'), [true, true, true, false, false]],
    ['tenant admin', as('TenantAdmin'), [false, false, false, false, false]],
  ])('%s', (_n, roles, expected) => {
    expect(STATES.map((s) => canEdit(s, roles))).toEqual(expected);
  });
});

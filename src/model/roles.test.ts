import { describe, expect, it } from 'vitest';
import type { PlanState } from '../api/types';
import { canEdit, rolesFrom } from './roles';

const as = (...roles: string[]) => rolesFrom((r) => roles.includes(r));
const STATES: PlanState[] = ['draft', 'calculated', 'in_review', 'signed', 'superseded'];

describe('canEdit', () => {
  it.each([
    ['field worker (Farmer)', as('Farmer'), [false, false, false, false, false]],
    ['holder (TenantAdmin)', as('TenantAdmin'), [true, true, false, false, false]],
    ['technician', as('TechnicalConsultant'), [true, true, true, false, false]],
    ['holder and technician', as('TenantAdmin', 'TechnicalConsultant'), [true, true, true, false, false]],
  ])('%s', (_n, roles, expected) => {
    expect(STATES.map((s) => canEdit(s, roles))).toEqual(expected);
  });
});

describe('rolesFrom (mirrors the backend role matrix)', () => {
  it.each([
    ['Farmer', { canWrite: false, technician: false, holder: false, canClose: false }],
    ['TenantAdmin', { canWrite: true, technician: false, holder: true, canClose: true }],
    ['TechnicalConsultant', { canWrite: true, technician: true, holder: false, canClose: false }],
  ])('%s', (role, expected) => {
    expect(as(role)).toEqual(expected);
  });
});

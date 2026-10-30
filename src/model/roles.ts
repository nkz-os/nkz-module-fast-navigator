import type { PlanState } from '../api/types';

export interface Roles { canWrite: boolean; technician: boolean }

export function rolesFrom(hasRole: (role: string) => boolean): Roles {
  const technician = hasRole('TechnicalConsultant');
  return { canWrite: technician || hasRole('Farmer'), technician };
}

/** Who may edit a plan in a state (backend `app/plans/states.py`): the role gate and the state gate. */
export function canEdit(state: PlanState, roles: Roles): boolean {
  if (state === 'draft' || state === 'calculated') return roles.canWrite;
  if (state === 'in_review') return roles.technician;
  return false;
}

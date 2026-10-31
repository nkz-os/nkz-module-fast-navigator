import type { PlanState } from '../api/types';

/**
 * Mirrors the backend role matrix (`app/plans/states.py`, owner 2026-10-31).
 * In this platform `Farmer` is the field worker (read only); `TenantAdmin` stands for the farm holder.
 */
export interface Roles {
  /** Create / edit / calculate / submit / revise: holder or technician. */
  canWrite: boolean;
  /** Review, justified N adjustment, return, sign, advisor profile, holder qualification. */
  technician: boolean;
  /** The farm holder (TenantAdmin). */
  holder: boolean;
  /** Close a plan (the holder's acceptance). The backend also refuses the user who signed it. */
  canClose: boolean;
}

export function rolesFrom(hasRole: (role: string) => boolean): Roles {
  const technician = hasRole('TechnicalConsultant');
  const holder = hasRole('TenantAdmin');
  return { canWrite: technician || holder, technician, holder, canClose: holder };
}

/** Who may edit a plan in a state (backend `app/plans/states.py`): the role gate and the state gate. */
export function canEdit(state: PlanState, roles: Roles): boolean {
  if (state === 'draft' || state === 'calculated') return roles.canWrite;
  if (state === 'in_review') return roles.technician;
  return false;
}

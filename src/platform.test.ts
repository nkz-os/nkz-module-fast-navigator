import { describe, expect, it, vi } from 'vitest';
import manifest from '../manifest.json';
vi.mock('@nekazari/module-kit', () => ({ defineModule: (m: unknown) => m }));
vi.mock('@nekazari/sdk', () => ({ i18n: {} }));
import mod, { MODULE_ROLES, MODULE_ROUTE } from './Module';

describe('platform contract', () => {
  it('declares route and roles, so a publish never narrows them to Farmer', () => {
    const m = mod as unknown as { id: string; route: string; requiredRoles: string[]; hostApiVersion: string };
    expect(m.id).toBe('fast-navigator');
    expect(m.route).toBe('/fast-navigator');
    expect(m.requiredRoles).toEqual(['Farmer', 'TechnicalConsultant', 'TenantAdmin']);
    expect(m.hostApiVersion).toBe('^2.0.0');
  });
  it('the seed manifest says the same as defineModule()', () => {
    expect(manifest.route_path).toBe(MODULE_ROUTE);
    expect(manifest.required_roles).toEqual([...MODULE_ROLES]);
  });
});

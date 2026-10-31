/**
 * Module entry point — canonical `defineModule()` pattern (Module Federation 2.0).
 *
 * `defineModule()` is the runtime source of truth: every publish overwrites the marketplace row's
 * route, roles and version with what is declared here. `manifest.json` and `k8s/registration.sql`
 * are only seeds and must say the same.
 */
import { defineModule } from '@nekazari/module-kit';
import { lazy } from 'react';
import './i18n';
import { moduleSlots } from './slots';
import pkg from '../package.json';

export const MODULE_ID = 'fast-navigator';
export const MODULE_ROUTE = '/fast-navigator';
export const MODULE_ROLES = ['Farmer', 'TechnicalConsultant', 'TenantAdmin'] as const;

const MainPage = lazy(() => import('./App'));

export default defineModule({
  id: MODULE_ID,
  displayName: 'FaST · Plan de abonado',
  version: pkg.version,
  hostApiVersion: '^2.0.0',
  route: MODULE_ROUTE,
  requiredRoles: [...MODULE_ROLES],
  description: 'Legal fertilisation plan per farm and campaign (RD 1051/2022)',
  accent: { base: '#10B981', soft: '#D1FAE5', strong: '#047857' },
  icon: 'leaf',
  navigation: {
    section: 'modules',
    priority: 50,
    label: {
      es: 'FaST · Plan de abonado',
      en: 'FaST · Nutrient plan',
      ca: 'FaST · Pla d\'adobat',
      eu: 'FaST · Ongarritze-plana',
      fr: 'FaST · Plan de fertilisation',
      pt: 'FaST · Plano de fertilização',
    },
  },
  main: MainPage,
  slots: moduleSlots as never,
});

import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

vi.mock('@nekazari/sdk', async () => {
  const { esT } = await import('../test/esT');
  return { useTranslation: () => ({ t: esT, i18n: { language: 'es' } }), i18n: {} };
});
let cropNameAnswer: string | null = 'Trigo blando';
vi.mock('../hooks/useCrops', async () => {
  const fx = await import('../test/fixtures/source-crops.json');
  return { useCrops: () => ({ data: fx.crops, error: null, loading: false, retry: () => undefined }) };
});
vi.mock('../hooks/useLoad', () => ({ useLoad: () => ({ data: cropNameAnswer, error: null, loading: false, retry: vi.fn() }) }));

import { FastApiError } from '../api/client';
import type { CampaignParcels, Plan } from '../api/types';
import fixture from '../test/fixtures/campaign-parcels.json';
import { defaultManagement, groupParcels, type GroupManagement } from '../model/sheets';
import { Wizard } from './Wizard';

const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v));
const PARCELS = fixture as unknown as CampaignParcels;
const PLAN = { id: 'p', campaign: 2027, state: 'draft', row_version: 1, sheets: [], rain_normal: null } as unknown as Plan;
const noop = () => undefined;
/** The attributes of the button that carries `label`. */
const buttonAttrs = (html: string, label: string) => new RegExp(`<button([^>]*)>(?:<[^>]+>)*[^<]*${label}`).exec(html)?.[1] ?? null;
const isDisabled = (html: string, label: string) => /\sdisabled(=""|\s|$)/.test(buttonAttrs(html, label) ?? '');

const chosenWheat = (parcels: CampaignParcels): Record<string, GroupManagement> => {
  const g = groupParcels(parcels.parcels)[0];
  return { [g.id]: { ...defaultManagement(g), irrigated: false, tillage: true, rotationYears: 4 } };
};

describe('Wizard (es)', () => {
  it('step 1 lists the group with its crop name, parcels and area, and the parcels without a crop apart', () => {
    cropNameAnswer = 'Trigo blando';
    const html = renderToStaticMarkup(<Wizard plan={PLAN} parcels={PARCELS} onSaved={noop} />);
    expect(html).toContain('Trigo blando');
    expect(html).toContain('1 parcela');
    expect(html).toContain('10,0 ha');
    expect(html).toContain('Sin cultivo para 2027 (1)');
    expect(html).toContain('✕ falta');
  });

  it('declares the crop of the parcels without one by name, not by code', () => {
    cropNameAnswer = 'Trigo blando';
    const html = renderToStaticMarkup(<Wizard plan={PLAN} parcels={PARCELS} onSaved={noop} />);
    expect(html).toContain('Escribe el nombre del cultivo…');
    expect(html).not.toContain('código EPPO');
    expect(html).not.toContain('p. ej. TRZAX');
  });

  it('shows the EPPO code when the name cannot be had', () => {
    cropNameAnswer = null;
    const html = renderToStaticMarkup(<Wizard plan={PLAN} parcels={PARCELS} onSaved={noop} />);
    expect(html).toContain('TRZAX');
  });

  it('marks a planned cycle with the link back to BioOrch and a sown one with its date', () => {
    cropNameAnswer = 'Trigo blando';
    const planned = clone(PARCELS);
    planned.parcels[1].cycle!.start.provenance = 'planned';
    const p = renderToStaticMarkup(<Wizard plan={PLAN} parcels={planned} onSaved={noop} />);
    expect(p).toContain('○ planificado en BioOrch');
    expect(p).toContain('href="/bioorchestrator?parcel=urn%3Angsi-ld%3AAgriParcel%3Ap1&amp;campaign=2027"');
    const sown = clone(PARCELS);
    sown.parcels[1].cycle!.start.provenance = 'actual';
    const s = renderToStaticMarkup(<Wizard plan={PLAN} parcels={sown} onSaved={noop} />);
    expect(s).toContain('● sembrado 25/10/2026');
  });

  it('step 2 cannot save while a group has no regime or no tillage chosen', () => {
    const html = renderToStaticMarkup(
      <Wizard plan={PLAN} parcels={PARCELS} onSaved={noop} initial={{ step: 2 }} />);
    expect(isDisabled(html, 'Guardar y calcular')).toBe(true);
    expect(html).toContain('Elige secano o regadío');
  });

  it('step 2 can save once everything is chosen', () => {
    const html = renderToStaticMarkup(
      <Wizard plan={PLAN} parcels={PARCELS} onSaved={noop} initial={{ step: 2, management: chosenWheat(PARCELS) }} />);
    expect(buttonAttrs(html, 'Guardar y calcular')).not.toBeNull();
    expect(isDisabled(html, 'Guardar y calcular')).toBe(false);
  });

  it('step 3 offers the rainfall and, if it times out, says so and still lets the plan be saved', () => {
    const html = renderToStaticMarkup(
      <Wizard plan={PLAN} parcels={PARCELS} onSaved={noop}
        initial={{ step: 3, management: chosenWheat(PARCELS), rainError: new FastApiError(502, null) }} />);
    expect(html).toContain('Obtener lluvia normal');
    expect(html).toContain('Tardó demasiado; reintenta.');
    expect(buttonAttrs(html, 'Guardar y calcular')).not.toBeNull();
    expect(isDisabled(html, 'Guardar y calcular')).toBe(false);
  });

  it('keeps existing sheets and lists them for removal', () => {
    const withSheet = { ...PLAN, sheets: [{ key: 'old', parcels: [{ urn: 'urn:ngsi-ld:AgriParcel:zz', sigpac: null }], overrides: [{ param: 'soil.ph' }] }] } as unknown as Plan;
    const html = renderToStaticMarkup(<Wizard plan={withSheet} parcels={PARCELS} onSaved={noop} />);
    expect(html).toContain('Hojas que ya tiene el plan');
    expect(html).toContain('Quitar');
  });
});

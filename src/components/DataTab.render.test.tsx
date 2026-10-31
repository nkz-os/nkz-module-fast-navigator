import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

vi.mock('@nekazari/sdk', async () => {
  const { esT } = await import('../test/esT');
  return { useTranslation: () => ({ t: esT, i18n: { language: 'es' } }), i18n: {} };
});
vi.mock('../hooks/useCrops', async () => {
  const fx = await import('../test/fixtures/source-crops.json');
  return { useCrops: () => ({ data: fx.crops, error: null, loading: false, retry: () => undefined }) };
});
vi.mock('../hooks/useLoad', () => ({ useLoad: () => ({ data: 'Trigo blando', error: null, loading: false, retry: vi.fn() }) }));

import type { PlanSheet } from '../api/types';
import { clone, COMPLETE, INCOMPLETE, makePlan, makeSheet, PARCELS, URN } from '../test/builders';
import { rolesFrom } from '../model/roles';
import { DataTab } from './DataTab';

const FARMER = rolesFrom((r) => r === 'TenantAdmin');      // the holder: non-technician editor
const TECH = rolesFrom((r) => r === 'TechnicalConsultant');
const noop = () => undefined;
const plain = (html: string) => html.replace(/<!-- -->/g, '');

const render = (sheet: PlanSheet, editable = true, roles = FARMER) =>
  renderToStaticMarkup(<DataTab plan={makePlan({ sheets: [sheet] })} sheet={sheet} parcels={PARCELS.parcels}
    editable={editable} roles={roles} onSaved={noop} onReload={noop} />);

describe('DataTab (es)', () => {
  it('lists what is missing, who provides it and the link to the owner', () => {
    const html = render(makeSheet({ result: clone(INCOMPLETE) }));
    expect(html).toContain('Faltan 5 datos para completar el cálculo');
    expect(html).toContain('Análisis de suelo (textura, pH, P, K)');
    expect(html).toContain('href="/module/soil?parcel=p1&amp;tab=manual"');
  });

  it('a missing value is a dash with the missing chip, a measured one carries its chip', () => {
    const html = render(makeSheet({ result: clone(INCOMPLETE) }));
    expect(html).toContain('✕ falta');
    expect(html).toContain('>—<');
    const ok = render(makeSheet());
    expect(ok).toContain('● medido');
    expect(ok).toContain('Trigo blando');
  });

  it('translates the notices of the calculation', () => {
    const html = render(makeSheet());
    expect(html).toContain('Sin N mínimo del producto para TRZAX: se usa el N típico.');
  });

  it('a parcel without an identifier asks for one', () => {
    expect(render(makeSheet())).toContain('Escribir SIGPAC');
  });

  it('read only draws no input and no save button', () => {
    const html = render(makeSheet(), false);
    expect(html).not.toContain('<input');
    expect(html).not.toContain('<textarea');
    expect(html).not.toContain('Guardar cambios');
    expect(html).not.toContain('>Ajustar<');
  });

  it('the farmer can adjust only the availability of organic inputs', () => {
    const result = clone(COMPLETE);
    result.inputs['organic.0.availability'] = { value: 0.35, provenance: 'table:mapa2010', source: 'engine', note: null };
    const sheet = makeSheet({
      result,
      inputs: { ...makeSheet().inputs, organic: [{ material: 'Estiércol', rate_t_ha: 20, n_pct: 0.6, p2o5_pct: 0.3, k2o_pct: 0.5 }] },
    });
    const farmer = render(sheet);
    expect(farmer.split('>Ajustar<').length - 1).toBe(1);
    const tech = render(sheet, true, TECH);
    expect(tech.split('>Ajustar<').length - 1).toBeGreaterThan(1);
  });

  it('shows the technician adjustment as an adjusted value with its chip', () => {
    const result = clone(COMPLETE);
    result.inputs['soil.ph'] = { value: 7.2, provenance: 'entered', source: 'user:u1@2026-10-01', note: 'lab repeat' };
    expect(render(makeSheet({ result }))).toContain('⚑ ajustado');
  });

  it('shows the stored SIGPAC of a parcel', () => {
    const sheet = makeSheet({ parcels: [{ urn: URN, sigpac: '31:201:0:0:12:45:1' }] });
    expect(render(sheet, false)).toContain('31:201:0:0:12:45:1');
  });

  it('chooses the declared and previous crop by name, with the fallow one click away', () => {
    const html = plain(render(makeSheet()));
    expect(html).toContain('Cultivo declarado');
    expect(html).toContain('Escribe el nombre del cultivo…');
    expect(html).toContain('>Barbecho<');
    expect(html).toContain('>Trigo blando<');
    expect(html).toContain('>Garbanzo · sin coeficientes<');
    expect(html).not.toContain('código EPPO');
  });

  it('a picked crop without coefficients is shown and marked', () => {
    const sheet = makeSheet({ inputs: { ...makeSheet().inputs, crop_eppo: 'CIEAR', previous_crop_eppo: 'fallow' } });
    const html = plain(render(sheet));
    expect(html).toContain('Garbanzo');
    expect(html).toContain('sin coeficientes');
    expect(html).toContain('FaST aún no tiene coeficientes de este cultivo');
    expect(html).toContain('>Barbecho<');
  });

  it('offers to apply the previous crop to the other sheets that lack one', () => {
    const lacking = (key: string) => {
      const result = clone(COMPLETE);
      result.inputs['previous_crop.eppo'] = { value: null, provenance: 'missing', source: null, note: null };
      return makeSheet({ key, result });
    };
    const a = lacking('a');
    const withPrev = { ...a, inputs: { ...a.inputs, previous_crop_eppo: 'fallow' } };
    const plan = makePlan({ sheets: [withPrev, lacking('b'), lacking('c')] });
    const html = renderToStaticMarkup(<DataTab plan={plan} sheet={withPrev} parcels={PARCELS.parcels}
      editable roles={FARMER} onSaved={noop} onReload={noop} />);
    expect(html).toContain('Aplicar a las otras 2 hojas sin cultivo anterior');
    expect(render(makeSheet())).not.toContain('Aplicar a las otras');
  });

  it('hints the cover crop grown before the main crop', () => {
    const parcels = clone(PARCELS.parcels);
    parcels.find((p) => p.id === URN)!.cover_before = 'VICSA';
    const html = renderToStaticMarkup(<DataTab plan={makePlan()} sheet={makeSheet()} parcels={parcels}
      editable roles={FARMER} onSaved={noop} onReload={noop} />);
    expect(html).toContain('Antes: cubierta de');
  });

  it('writes the unit and the help of the expected yield and of the CV', () => {
    const sheet = makeSheet({ inputs: { ...makeSheet().inputs, declared_yields: { '2026': 3000 } } });
    const html = render(sheet);
    expect(html).toContain('kg/ha (grano en fresco)');
    expect(html).toContain('Con 3 años, la variabilidad (CV) se calcula sola');
    expect(html).toContain('El CV mide cuánto varía la cosecha');
  });

  it('the organic material is one of the five types, translated', () => {
    const organic = [{ material: 'slurry', rate_t_ha: 20, n_pct: 0.6, p2o5_pct: 0.3, k2o_pct: 0.5 }];
    const sheet = makeSheet({ inputs: { ...makeSheet().inputs, organic } });
    expect(render(sheet, false)).toContain('Purín · 20 t/ha');
    const blank = makeSheet({ inputs: { ...makeSheet().inputs, organic: [{ ...organic[0], material: '' }] } });
    expect(render(blank)).toContain('Elige el tipo de material de cada aporte para guardar.');
  });

  it('shows the estimated organic matter notice', () => {
    const result = clone(COMPLETE);
    result.notices = [{ code: 'soil_om_estimated', params: { oc_pct: 2.08, om_pct: 3.59 } }];
    expect(render(makeSheet({ result }))).toContain('Materia orgánica estimada (3.59 %)');
  });

  it('adding a declared year starts as a button and puts no zero row in the sheet', () => {
    const h = render(makeSheet());
    expect(h).toContain('+ Declarar un año');
    expect(h).not.toContain('Rendimiento declarado');
    expect(h).not.toContain('value="0"');
  });
});

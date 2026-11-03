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
vi.mock('../hooks/useOrganicProducts', () => ({
  useOrganicProducts: () => ({
    data: {
      products: [{
        id: 'cattle_manure_table', material: 'cattle_manure', basis: 'fresh', source_ref: 'MAPA 2010, ch. 6, p. 47, table 6.7',
        n_pct: { value: 0.45, min: 0.3, max: 0.6 }, p2o5_pct: { value: 0.25, min: 0.1, max: 0.4 }, k2o_pct: { value: 0.7, min: 0.4, max: 1 },
        names: { es: 'Estiércol de vacuno', en: 'Cattle manure' },
      }],
      attribution: { source_id: 'mapa_guia_2010', text: 'Ministerio de Agricultura (2010). Ley 37/2007.' },
    },
    error: null, loading: false, retry: () => undefined,
  }),
}));
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

  it('lists every enclosure of the parcel and asks for no typed SIGPAC', () => {
    const result = clone(COMPLETE);
    result.inputs[`parcel.${URN}.enclosures`] = {
      value: [{ reference: '31:97:0:0:4:228:1', overlap_pct: 43.36 }, { reference: '31:97:0:0:4:90020:1', overlap_pct: 29.41 }],
      provenance: 'measured', source: 'broker', note: null,
    };
    const html = render(makeSheet({ result }));
    expect(html).toContain('31:97:0:0:4:228:1 (43.36 %)');
    expect(html).toContain('31:97:0:0:4:90020:1 (29.41 %)');
    expect(html).not.toContain('Escribir SIGPAC');
    expect(html).not.toContain('placeholder="31:201:0:0:12:45:1"');
  });

  it('broker enclosures win over an older typed SIGPAC', () => {
    const result = clone(COMPLETE);
    result.inputs[`parcel.${URN}.enclosures`] = {
      value: [{ reference: '31:97:0:0:4:228:1', overlap_pct: 43.36 }], provenance: 'measured', source: 'broker', note: null,
    };
    const html = render(makeSheet({ result, parcels: [{ urn: URN, sigpac: '31:201:0:0:12:45:1' }] }));
    expect(html).toContain('31:97:0:0:4:228:1 (43.36 %)');
    expect(html).not.toContain('31:201:0:0:12:45:1');
  });

  it('preselects the farmland enclosures and lets the editor tick the rest', () => {
    const result = clone(COMPLETE);
    result.inputs[`parcel.${URN}.enclosures`] = {
      value: [
        { reference: '31:125:0:0:2:729:1', overlap_pct: 84.27, sigpac_use: 'TA', selected: true },
        { reference: '31:125:0:0:2:9001:1', overlap_pct: 3, sigpac_use: 'CA', selected: false },
      ],
      provenance: 'measured', source: 'broker', note: null,
    };
    const html = plain(render(makeSheet({ result })));
    expect(html).toContain('31:125:0:0:2:729:1 (84.27 %) · Tierra arable');
    expect(html).toContain('31:125:0:0:2:9001:1 (3 %) · Viales');
    expect(html.match(/type="checkbox"/g)).toHaveLength(2);
    expect(html.match(/type="checkbox"[^>]*checked/g)).toHaveLength(1);
    expect(html).toContain('Solo cuentan los recintos marcados');
  });

  it('a stored choice of enclosures wins over the default', () => {
    const result = clone(COMPLETE);
    result.inputs[`parcel.${URN}.enclosures`] = {
      value: [
        { reference: '31:125:0:0:2:729:1', overlap_pct: 84.27, sigpac_use: 'TA', selected: true },
        { reference: '31:125:0:0:2:9001:1', overlap_pct: 3, sigpac_use: 'CA', selected: false },
      ],
      provenance: 'measured', source: 'broker', note: null,
    };
    const sheet = makeSheet({ result, inputs: { ...makeSheet().inputs, enclosures: { [URN]: ['31:125:0:0:2:9001:1'] } } });
    const html = plain(render(sheet));
    expect(html.match(/type="checkbox"[^>]*checked/g)).toHaveLength(1);
    expect(html).toMatch(/type="checkbox"[^>]*checked[^>]*>[\s\S]{0,400}31:125:0:0:2:9001:1/);
  });

  it('read-only, the unticked enclosures are shown as left out', () => {
    const result = clone(COMPLETE);
    result.inputs[`parcel.${URN}.enclosures`] = {
      value: [
        { reference: '31:125:0:0:2:729:1', overlap_pct: 84.27, sigpac_use: 'TA', selected: true },
        { reference: '31:125:0:0:2:9001:1', overlap_pct: 3, sigpac_use: 'CA', selected: false },
      ],
      provenance: 'measured', source: 'broker', note: null,
    };
    const html = plain(render(makeSheet({ result }), false));
    expect(html).not.toContain('type="checkbox"');
    expect(html).toContain('31:125:0:0:2:9001:1 (3 %) · Viales · fuera del plan');
    expect(html).not.toContain('31:125:0:0:2:729:1 (84.27 %) · Tierra arable · fuera del plan');
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

  it('offers the MAPA products, shows the suggestion with its labelled range and the attribution', () => {
    const organic = [{ material: 'cattle_manure', rate_t_ha: 20, n_pct: 0.45, p2o5_pct: 0.25, k2o_pct: 0.7, composition_source: 'table:mapa_guia_2010' as const }];
    const html = plain(render(makeSheet({ inputs: { ...makeSheet().inputs, organic } })));
    expect(html).toContain('Producto (sugerencia MAPA)');
    expect(html).toContain('Origen de la composición');
    expect(html).toContain('▤ tabla');
    expect(html).toContain('Valor orientativo de la guía MAPA');
    expect(html).toContain('Ley 37/2007');
  });

  it('a declared composition shows the declared chip and no suggestion hint', () => {
    const organic = [{ material: 'slurry', rate_t_ha: 20, n_pct: 0.6, p2o5_pct: 0.3, k2o_pct: 0.5 }];
    const html = plain(render(makeSheet({ inputs: { ...makeSheet().inputs, organic } })));
    expect(html).toContain('◐ declarado');
    expect(html).not.toContain('Valor orientativo de la guía MAPA');
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

  it('residues: the table value is shown with its chip and neither button is on', () => {
    const result = clone(COMPLETE);
    result.inputs['crop.residue_left_pct'] = { value: 30, provenance: 'table:panagos_2022', source: 'bioorch', note: null };
    const html = plain(render(makeSheet({ result })));
    expect(html).toContain('Se quedan en campo');
    expect(html).toContain('Se retiran');
    expect(html).toContain('▤ tabla');
    expect(html).not.toContain('aria-pressed="true"');
  });

  it('residues: a declared choice turns its button on, the other stays off', () => {
    const result = clone(COMPLETE);
    result.inputs['crop.residue_left_pct'] = { value: 100, provenance: 'declared', source: 'plan', note: null };
    const html = plain(render(makeSheet({ result, inputs: { ...makeSheet().inputs, residues: 'left' } })));
    expect(html.match(/aria-pressed="true"/g)).toHaveLength(1);
    expect(html).toMatch(/aria-pressed="true"[^>]*>(?:<[^>]+>)*Se quedan en campo/);
    expect(html).toContain('◐ declarado');
  });

  it('residues: missing shows ✕ falta and read only disables the buttons', () => {
    const result = clone(COMPLETE);
    result.inputs['crop.residue_left_pct'] = { value: null, provenance: 'missing', source: null, note: null };
    expect(plain(render(makeSheet({ result })))).toContain('✕ falta');
    const ro = render(makeSheet({ result }), false);
    expect(/<button([^>]*)>(?:<[^>]+>)*Se retiran/.exec(ro)?.[1]).toMatch(/\sdisabled/);
  });

  it('previous residues: two buttons next to the previous crop, hidden for a fallow', () => {
    const result = clone(COMPLETE);
    result.inputs['previous_crop.residue_left_pct'] = { value: 0, provenance: 'declared', source: 'plan', note: null };
    const prev = (eppo: string) => plain(render(makeSheet({ result, inputs: { ...makeSheet().inputs, previous_crop_eppo: eppo, previous_residues: 'removed' } })));
    const h = prev('CIEAR');
    expect(h).toContain('Restos del cultivo anterior');
    expect(h).toContain('Se quedaron en campo');
    expect(h).toMatch(/aria-pressed="true"[^>]*>(?:<[^>]+>)*Se retiraron/);
    expect(prev('fallow')).not.toContain('Restos del cultivo anterior');
  });
});

import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

vi.mock('@nekazari/sdk', async () => {
  const { esT } = await import('../test/esT');
  return { useTranslation: () => ({ t: esT, i18n: { language: 'es' } }), i18n: {} };
});

import type { SheetResult } from '../api/types';
import { formatKgHa } from '../model/format';
import { clone, COMPLETE, INCOMPLETE } from '../test/builders';
import { NeedsTab } from './NeedsTab';

const k = (v: number) => formatKgHa(v, 'es');

describe('NeedsTab (es)', () => {
  const html = renderToStaticMarkup(<NeedsTab result={COMPLETE} />);
  const n = COMPLETE.n!;

  it('draws the band as min, mean and max in whole numbers, and the range before credits', () => {
    expect(html).toContain('mín');
    expect(html).toContain('medio');
    expect(html).toContain('máx');
    for (const v of [n.min_kg_ha, n.avg_kg_ha, n.max_kg_ha]) expect(html).toContain(`<strong>${k(v)}</strong>`);
    expect(html).toContain('antes de créditos');
  });

  it('marks the nine yield levels, each with its figure', () => {
    expect(html.match(/aria-label="Nivel de rendimiento \d/g)).toHaveLength(9);
  });

  it('shows the breakdown with a chip per sourced row and the fixed citation of Nend', () => {
    expect(html).toContain('Desglose');
    expect(html).toContain('Extracción del cultivo');
    expect(html).toContain('Villalobos 2020, tabla 4');
    expect(html).toContain('● medido');
  });

  it('P2O5 and K2O show the class the engine decided and the dose in whole kg/ha', () => {
    expect(html).toContain('Suelo: Bajo');
    expect(html).toContain(`<strong>${k(COMPLETE.p2o5!.rate_kg_ha)}</strong>`);
    expect(html).toContain('subida + exportación');
    expect(html).toContain('K₂O');
  });

  it('writes the engine versions', () => {
    expect(html).toContain('Versiones: motor 1.1.0 · cálculo 1.2.0');
  });

  it('an incomplete result without N draws the gap and no band, never zeros', () => {
    const r: SheetResult = { ...clone(INCOMPLETE), n: null };
    const out = renderToStaticMarkup(<NeedsTab result={r} />);
    expect(out).toContain('N sin calcular: faltan');
    expect(out).toContain('Análisis de suelo');
    expect(out).not.toContain('antes de créditos');
    expect(out).not.toContain('aria-label="Nivel de rendimiento');
  });

  it('P and K missing are said, not drawn', () => {
    const r: SheetResult = { ...clone(INCOMPLETE), p2o5: null, k2o: null };
    expect(renderToStaticMarkup(<NeedsTab result={r} />)).toContain('K₂O sin calcular: faltan');
  });

  it('flags a provisional result', () => {
    expect(renderToStaticMarkup(<NeedsTab result={{ ...clone(COMPLETE), provisional: true }} />)).toContain('provisional');
  });

  it('strategy 4 says the soil is ignored instead of drawing a class', () => {
    const r = clone(COMPLETE);
    r.p2o5 = { ...r.p2o5!, soil_class: null, threshold_mg_kg: null, high_from_mg_kg: null, basis: 'export', strategy: 4 };
    const out = renderToStaticMarkup(<NeedsTab result={r} />);
    expect(out).toContain('Estrategia 4: no se tiene en cuenta el suelo');
  });

  it('before the first calculation it says so', () => {
    expect(renderToStaticMarkup(<NeedsTab result={null} />)).toContain('Todavía no hay cálculo');
  });
});

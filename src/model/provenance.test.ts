import { describe, expect, it } from 'vitest';
import type { CycleView, Sourced } from '../api/types';
import { chipFor } from './provenance';

const s = (provenance: string, extra: Partial<Sourced> = {}): Sourced => ({ value: 1, provenance, source: 'src', note: null, ...extra });
const planned: CycleView = { crop_id: 'c', start: { date: '2026-10-25', provenance: 'planned' }, pending: false, status: null };
const actual: CycleView = { ...planned, start: { date: '2026-10-25', provenance: 'actual' } };

describe('chipFor', () => {
  it('measured', () => expect(chipFor(s('measured'))).toMatchObject({ symbol: '●', key: 'provenance.measured', intent: 'positive' }));
  it('table', () => expect(chipFor(s('table:mapa2010'))).toMatchObject({ symbol: '▤', intent: 'default', tooltip: { params: { id: 'mapa2010' } } }));
  it('declared', () => expect(chipFor(s('declared'))).toMatchObject({ symbol: '◐', intent: 'default' }));
  it('entered carries the reason', () => {
    const c = chipFor(s('entered', { note: 'lab', source: 'user:u1@2026-10-01' }));
    expect(c).toMatchObject({ symbol: '⚑', intent: 'info' });
    expect(c.tooltip.params).toEqual({ note: 'lab', source: 'user:u1@2026-10-01' });
  });
  it('estimated', () => expect(chipFor(s('estimated'))).toMatchObject({ symbol: '≈', intent: 'warning' }));
  it('missing', () => expect(chipFor(s('missing', { value: null }))).toMatchObject({ symbol: '✕', intent: 'negative', key: 'provenance.missing' }));
  it('no value at all is missing', () => expect(chipFor(null).symbol).toBe('✕'));
  it('a crop of a planned cycle', () => expect(chipFor(s('measured'), planned)).toMatchObject({ symbol: '○', key: 'provenance.plannedBioorch' }));
  it('a crop of a sown cycle stays measured', () => expect(chipFor(s('measured'), actual).symbol).toBe('●'));
  it('an unknown provenance is not hidden', () => expect(chipFor(s('weird')).key).toBe('provenance.unknown'));
});
